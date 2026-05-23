/* SPDX-License-Identifier: GPL-2.0 */
/*
 * sec_ts wakelock 兼容垫片
 *
 * sec_ts 是 Android 系 vendor 驱动，用老 wakelock API（struct wake_lock /
 * wake_lock_init / wake_lock_timeout），该 API 由 <linux/wakelock.h> 提供。
 * 该头早已从主线内核移除（被 wakeup_source 取代）：
 *   - Rockchip BSP 内核（rock5b, linux-6.1-rkr5.1）自带 Android 兼容
 *     <linux/wakelock.h>，走原生路径，本垫片不介入；
 *   - Allwinner A733 BSP（radxa-cubie-a7a, linux-5.15）等主线系内核无此头，
 *     回退到本垫片，把老 API 映射到现代 wakeup_source（pm_wakeup.h）。
 *
 * 用 __has_include 在编译期分流，保证既有 board（rock5b）行为零变化。
 */
#ifndef SEC_TS_WAKELOCK_COMPAT_H
#define SEC_TS_WAKELOCK_COMPAT_H

#if defined(__has_include) && __has_include(<linux/wakelock.h>)

#include <linux/wakelock.h>

#else /* 内核无 <linux/wakelock.h>：映射到现代 wakeup_source */

#include <linux/device.h>
#include <linux/jiffies.h>
#include <linux/pm_wakeup.h>

#define WAKE_LOCK_SUSPEND 0

struct wake_lock {
	struct wakeup_source *ws;
};

static inline void wake_lock_init(struct wake_lock *wl, int type,
				  const char *name)
{
	wl->ws = wakeup_source_register(NULL, name);
}

static inline void wake_lock_destroy(struct wake_lock *wl)
{
	if (wl->ws) {
		wakeup_source_unregister(wl->ws);
		wl->ws = NULL;
	}
}

static inline void wake_lock(struct wake_lock *wl)
{
	if (wl->ws)
		__pm_stay_awake(wl->ws);
}

static inline void wake_unlock(struct wake_lock *wl)
{
	if (wl->ws)
		__pm_relax(wl->ws);
}

static inline void wake_lock_timeout(struct wake_lock *wl, long timeout)
{
	if (wl->ws)
		__pm_wakeup_event(wl->ws, jiffies_to_msecs(timeout));
}

#endif /* __has_include(<linux/wakelock.h>) */

#endif /* SEC_TS_WAKELOCK_COMPAT_H */
