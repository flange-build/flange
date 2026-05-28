// SPDX-License-Identifier: GPL-2.0-only
/*
 * Meizu E3 (s6d6ft0 Tianma FHD 1080x2160) MIPI-DSI panel driver
 *
 * E3 是「IC 自配置」傻屏：所有 timing/PLL/lane 由屏内部预设，主控只需
 * 在 4-lane MIPI 上发 sleep-out + display-on 两条 DCS 命令即可点亮。
 *
 * 本驱动形态参照 mainline drivers/gpu/drm/panel/panel-himax-hx8394.c，
 * 仅保留 drm_panel 必需骨架（prepare/unprepare/enable/disable/get_modes）。
 *
 * 显示参数（高通原厂 panel DT 权威值，a7a 实板验证）：
 *   active   = 1080 × 2160
 *   htotal   = 1317（hfp=229 / hbp=4 / hsync=4）
 *   vtotal   = 2176（vfp=8  / vbp=6 / vsync=2）
 *   refresh  = 60 Hz
 *   pclk     ≈ 171.95 MHz
 *
 * DSI 模式：4-lane RGB888 video，**非 burst**（burst 在 A733/QCS6490
 * 实测出竖条纹/抖动；E3 同 timing 在 rock5b 也只在非 burst 稳定）。
 *
 * 复位时序：active-low；assert 20ms → deassert → 等 120ms 后下 init。
 */

#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/regulator/consumer.h>

#include <drm/drm_mipi_dsi.h>
#include <drm/drm_modes.h>
#include <drm/drm_panel.h>

struct meizu_e3 {
	struct drm_panel panel;
	struct mipi_dsi_device *dsi;
	struct regulator *vdd;
	struct regulator *vccio;
	struct gpio_desc *reset_gpio;
	bool prepared;
};

static const struct drm_display_mode meizu_e3_mode = {
	.clock       = 171948,    /* kHz，~171.95 MHz */
	.hdisplay    = 1080,
	.hsync_start = 1080 + 229,
	.hsync_end   = 1080 + 229 + 4,
	.htotal      = 1080 + 229 + 4 + 4,  /* 1317 */
	.vdisplay    = 2160,
	.vsync_start = 2160 + 8,
	.vsync_end   = 2160 + 8 + 2,
	.vtotal      = 2160 + 8 + 2 + 6,    /* 2176 */
	.width_mm    = 68,    /* 物理尺寸约 68 × 136 mm（5.5"） */
	.height_mm   = 136,
};

static inline struct meizu_e3 *to_meizu_e3(struct drm_panel *panel)
{
	return container_of(panel, struct meizu_e3, panel);
}

static int meizu_e3_prepare(struct drm_panel *panel)
{
	struct meizu_e3 *ctx = to_meizu_e3(panel);
	int ret;

	if (ctx->prepared)
		return 0;

	ret = regulator_enable(ctx->vdd);
	if (ret) {
		dev_err(panel->dev, "failed to enable vdd: %d\n", ret);
		return ret;
	}
	ret = regulator_enable(ctx->vccio);
	if (ret) {
		dev_err(panel->dev, "failed to enable vccio: %d\n", ret);
		regulator_disable(ctx->vdd);
		return ret;
	}
	usleep_range(10000, 11000);

	/* 复位时序：active-low；assert 20ms → deassert → 等 120ms 后 init */
	gpiod_set_value_cansleep(ctx->reset_gpio, 1);
	msleep(20);
	gpiod_set_value_cansleep(ctx->reset_gpio, 0);
	msleep(120);

	ctx->prepared = true;
	return 0;
}

static int meizu_e3_unprepare(struct drm_panel *panel)
{
	struct meizu_e3 *ctx = to_meizu_e3(panel);

	if (!ctx->prepared)
		return 0;

	gpiod_set_value_cansleep(ctx->reset_gpio, 1);
	usleep_range(5000, 6000);
	regulator_disable(ctx->vccio);
	regulator_disable(ctx->vdd);
	ctx->prepared = false;
	return 0;
}

static int meizu_e3_enable(struct drm_panel *panel)
{
	struct meizu_e3 *ctx = to_meizu_e3(panel);
	struct mipi_dsi_device *dsi = ctx->dsi;
	int ret;

	/* init sequence：sleep-out (0x11) + 120ms + display-on (0x29) + 10ms */
	ret = mipi_dsi_dcs_exit_sleep_mode(dsi);
	if (ret < 0) {
		dev_err(panel->dev, "exit sleep failed: %d\n", ret);
		return ret;
	}
	msleep(120);

	ret = mipi_dsi_dcs_set_display_on(dsi);
	if (ret < 0) {
		dev_err(panel->dev, "set display on failed: %d\n", ret);
		return ret;
	}
	msleep(10);

	return 0;
}

static int meizu_e3_disable(struct drm_panel *panel)
{
	struct mipi_dsi_device *dsi = to_meizu_e3(panel)->dsi;
	int ret;

	ret = mipi_dsi_dcs_set_display_off(dsi);
	if (ret < 0)
		dev_warn(panel->dev, "set display off failed: %d\n", ret);

	ret = mipi_dsi_dcs_enter_sleep_mode(dsi);
	if (ret < 0)
		dev_warn(panel->dev, "enter sleep failed: %d\n", ret);
	msleep(120);
	return 0;
}

static int meizu_e3_get_modes(struct drm_panel *panel,
			      struct drm_connector *connector)
{
	struct drm_display_mode *mode;

	mode = drm_mode_duplicate(connector->dev, &meizu_e3_mode);
	if (!mode)
		return -ENOMEM;

	mode->type = DRM_MODE_TYPE_DRIVER | DRM_MODE_TYPE_PREFERRED;
	drm_mode_set_name(mode);
	drm_mode_probed_add(connector, mode);

	connector->display_info.width_mm  = mode->width_mm;
	connector->display_info.height_mm = mode->height_mm;

	return 1;
}

static const struct drm_panel_funcs meizu_e3_funcs = {
	.prepare    = meizu_e3_prepare,
	.unprepare  = meizu_e3_unprepare,
	.enable     = meizu_e3_enable,
	.disable    = meizu_e3_disable,
	.get_modes  = meizu_e3_get_modes,
};

static int meizu_e3_probe(struct mipi_dsi_device *dsi)
{
	struct device *dev = &dsi->dev;
	struct meizu_e3 *ctx;
	int ret;

	ctx = devm_kzalloc(dev, sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;

	ctx->dsi = dsi;
	mipi_dsi_set_drvdata(dsi, ctx);

	ctx->vdd = devm_regulator_get(dev, "vdd");
	if (IS_ERR(ctx->vdd))
		return dev_err_probe(dev, PTR_ERR(ctx->vdd),
				     "failed to get vdd regulator\n");

	ctx->vccio = devm_regulator_get(dev, "vccio");
	if (IS_ERR(ctx->vccio))
		return dev_err_probe(dev, PTR_ERR(ctx->vccio),
				     "failed to get vccio regulator\n");

	ctx->reset_gpio = devm_gpiod_get(dev, "reset", GPIOD_OUT_HIGH);
	if (IS_ERR(ctx->reset_gpio))
		return dev_err_probe(dev, PTR_ERR(ctx->reset_gpio),
				     "failed to get reset gpio\n");

	dsi->lanes = 4;
	dsi->format = MIPI_DSI_FMT_RGB888;
	/* 非 burst video mode；MIPI_DSI_CLOCK_NON_CONTINUOUS 不开（与
	 * a7a 实板一致）。 */
	dsi->mode_flags = MIPI_DSI_MODE_VIDEO;

	drm_panel_init(&ctx->panel, dev, &meizu_e3_funcs,
		       DRM_MODE_CONNECTOR_DSI);

	ret = drm_panel_of_backlight(&ctx->panel);
	if (ret)
		return dev_err_probe(dev, ret, "failed to get backlight\n");

	drm_panel_add(&ctx->panel);

	ret = mipi_dsi_attach(dsi);
	if (ret < 0) {
		dev_err(dev, "mipi_dsi_attach failed: %d\n", ret);
		drm_panel_remove(&ctx->panel);
		return ret;
	}

	return 0;
}

static void meizu_e3_remove(struct mipi_dsi_device *dsi)
{
	struct meizu_e3 *ctx = mipi_dsi_get_drvdata(dsi);
	int ret;

	ret = mipi_dsi_detach(dsi);
	if (ret < 0)
		dev_err(&dsi->dev, "mipi_dsi_detach failed: %d\n", ret);

	drm_panel_remove(&ctx->panel);
}

static const struct of_device_id meizu_e3_of_match[] = {
	{ .compatible = "meizu,e3-panel" },
	{ }
};
MODULE_DEVICE_TABLE(of, meizu_e3_of_match);

static struct mipi_dsi_driver meizu_e3_driver = {
	.probe  = meizu_e3_probe,
	.remove = meizu_e3_remove,
	.driver = {
		.name           = "panel-meizu-e3",
		.of_match_table = meizu_e3_of_match,
	},
};
module_mipi_dsi_driver(meizu_e3_driver);

MODULE_AUTHOR("flange contributors");
MODULE_DESCRIPTION("Meizu E3 (s6d6ft0 Tianma FHD) MIPI-DSI panel driver");
MODULE_LICENSE("GPL");
