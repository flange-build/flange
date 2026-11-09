#include <Arduino_RouterBridge.h>

// Linux 调用回显接口；MCU 每秒向 Linux 发送递增计数，验证双向通信。
void setup()
{
	Bridge.begin();
	Bridge.provide("flange.echo", [](int value) { return value; });
}

void loop()
{
	static int sequence;

	Bridge.notify("flange.tick", sequence++);
	delay(1000);
}
