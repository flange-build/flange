@_silgen_name("rt_i2c_bus_device_find")
private func rt_i2c_bus_device_find(
    _ busName: UnsafePointer<CChar>?
) -> UnsafeMutableRawPointer?

@_silgen_name("rt_i2c_transfer")
private func rt_i2c_transfer(
    _ bus: UnsafeMutableRawPointer?,
    _ messages: UnsafeMutablePointer<RTI2CMessage>?,
    _ count: UInt32
) -> UInt

private let rtI2CReadFlag: UInt16 = 1
private let swiftI2CMaxTransferCount: UInt32 = 32

private var swiftI2CWriteBuffer = FixedByteBuffer32()
private var swiftI2CReadBuffer = FixedByteBuffer32()

public enum I2CStatus {
    public static let ok: Int32 = 0
    public static let invalidArgument: Int32 = -1
    public static let busNotFound: Int32 = -2
    public static let bufferOverflow: Int32 = -3
    public static let transferFailed: Int32 = -4
}

public struct I2CTransferResult {
    public let status: Int32
    public let readCount: UInt32

    public var isSuccess: Bool {
        status == I2CStatus.ok
    }
}

public struct I2CBus {
    public let index: UInt32

    public init(index: UInt32) {
        self.index = index
    }

    public func resetWriteBuffer() {
        swiftI2CWriteBuffer.reset()
        swiftI2CReadBuffer.reset()
    }

    public func appendWriteByte(_ byte: UInt8) -> Int32 {
        swiftI2CWriteBuffer.append(byte)
    }

    public func transfer(address: UInt16, readCount: UInt32) -> I2CTransferResult {
        let writeCount = swiftI2CWriteBuffer.count
        swiftI2CReadBuffer.reset()

        if (writeCount == 0 && readCount == 0) ||
            readCount > swiftI2CMaxTransferCount ||
            address > 0x7f ||
            index > 31 {
            return I2CTransferResult(
                status: I2CStatus.invalidArgument,
                readCount: 0
            )
        }

        let status = withI2CBusName(index: index) { busName in
            guard let bus = rt_i2c_bus_device_find(busName) else {
                return I2CStatus.busNotFound
            }

            var messages = (RTI2CMessage.empty, RTI2CMessage.empty)
            return swiftI2CWriteBuffer.withMutableBytes { writePointer in
                swiftI2CReadBuffer.withMutableBytes { readPointer in
                    withUnsafeMutablePointer(to: &messages) { pairPointer in
                        pairPointer.withMemoryRebound(
                            to: RTI2CMessage.self,
                            capacity: 2
                        ) { messagePointer in
                            var messageCount: UInt32 = 0
                            if writeCount > 0 {
                                messagePointer[Int(messageCount)] = RTI2CMessage(
                                    address: address,
                                    flags: 0,
                                    length: UInt16(writeCount),
                                    buffer: writePointer
                                )
                                messageCount += 1
                            }

                            if readCount > 0 {
                                messagePointer[Int(messageCount)] = RTI2CMessage(
                                    address: address,
                                    flags: rtI2CReadFlag,
                                    length: UInt16(readCount),
                                    buffer: readPointer
                                )
                                messageCount += 1
                            }

                            let transferred = rt_i2c_transfer(
                                bus,
                                messagePointer,
                                messageCount
                            )
                            if transferred != UInt(messageCount) {
                                return I2CStatus.transferFailed
                            }
                            return I2CStatus.ok
                        }
                    }
                }
            }
        }

        if status == I2CStatus.ok {
            swiftI2CReadBuffer.setCount(readCount)
            return I2CTransferResult(status: status, readCount: readCount)
        }

        swiftI2CReadBuffer.reset()
        return I2CTransferResult(status: status, readCount: 0)
    }

    public func readByte(at index: UInt32) -> UInt8 {
        swiftI2CReadBuffer.byte(at: index)
    }
}

private struct RTI2CMessage {
    var address: UInt16
    var flags: UInt16
    var length: UInt16
    var buffer: UnsafeMutablePointer<UInt8>?

    static var empty: RTI2CMessage {
        RTI2CMessage(
            address: 0,
            flags: 0,
            length: 0,
            buffer: nil
        )
    }
}

private struct FixedByteBuffer32 {
    private var storage: (
        UInt8, UInt8, UInt8, UInt8,
        UInt8, UInt8, UInt8, UInt8,
        UInt8, UInt8, UInt8, UInt8,
        UInt8, UInt8, UInt8, UInt8,
        UInt8, UInt8, UInt8, UInt8,
        UInt8, UInt8, UInt8, UInt8,
        UInt8, UInt8, UInt8, UInt8,
        UInt8, UInt8, UInt8, UInt8
    )

    private(set) var count: UInt32

    init() {
        storage = (
            0, 0, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0
        )
        count = 0
    }

    mutating func reset() {
        count = 0
    }

    mutating func append(_ byte: UInt8) -> Int32 {
        if count >= swiftI2CMaxTransferCount {
            return I2CStatus.bufferOverflow
        }

        let offset = count
        withMutableBytes { pointer in
            pointer[Int(offset)] = byte
        }
        count += 1
        return I2CStatus.ok
    }

    mutating func setCount(_ newCount: UInt32) {
        count = newCount <= swiftI2CMaxTransferCount ? newCount : swiftI2CMaxTransferCount
    }

    func byte(at index: UInt32) -> UInt8 {
        if index >= count {
            return 0
        }

        return withUnsafePointer(to: storage) { pointer in
            pointer.withMemoryRebound(to: UInt8.self, capacity: 32) {
                $0[Int(index)]
            }
        }
    }

    mutating func withMutableBytes<Result>(
        _ body: (UnsafeMutablePointer<UInt8>) -> Result
    ) -> Result {
        withUnsafeMutablePointer(to: &storage) { pointer in
            pointer.withMemoryRebound(to: UInt8.self, capacity: 32) {
                body($0)
            }
        }
    }
}

private func withI2CBusName<Result>(
    index: UInt32,
    _ body: (UnsafePointer<CChar>) -> Result
) -> Result {
    var name = (
        Int8(105),
        Int8(50),
        Int8(99),
        Int8(0),
        Int8(0),
        Int8(0)
    )

    if index >= 10 {
        name.3 = asciiDigit(index / 10)
        name.4 = asciiDigit(index % 10)
        name.5 = 0
    } else {
        name.3 = asciiDigit(index)
        name.4 = 0
    }

    return withUnsafePointer(to: &name) { pointer in
        pointer.withMemoryRebound(to: CChar.self, capacity: 6) {
            body($0)
        }
    }
}

private func asciiDigit(_ value: UInt32) -> Int8 {
    Int8(bitPattern: UInt8(48 + value))
}
