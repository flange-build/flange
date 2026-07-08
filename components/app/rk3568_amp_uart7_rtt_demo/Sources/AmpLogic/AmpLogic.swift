import RtThreadI2C
import RtThreadShell

@_cdecl("swift_handle_message")
public func swift_handle_message(
    _ input: UnsafePointer<UInt8>?,
    _ inputCount: UInt32,
    _ output: UnsafeMutablePointer<UInt8>?,
    _ outputCapacity: UInt32
) -> UInt32 {
    guard let output = output else {
        return 0
    }

    let responseLength = swiftResponseLength()
    let count = outputCapacity < responseLength ? outputCapacity : responseLength
    var index: UInt32 = 0
    while index < count {
        output[Int(index)] = swiftResponseByte(index)
        index += 1
    }
    return count
}

private func swiftResponseLength() -> UInt32 {
    return 17
}

private func swiftResponseByte(_ index: UInt32) -> UInt8 {
    switch index {
    case 0: return 83
    case 1: return 119
    case 2: return 105
    case 3: return 102
    case 4: return 116
    case 5: return 32
    case 6: return 114
    case 7: return 112
    case 8: return 109
    case 9: return 115
    case 10: return 103
    case 11: return 32
    case 12: return 101
    case 13: return 99
    case 14: return 104
    case 15: return 111
    case 16: return 33
    default: return 0
    }
}

@_cdecl("swift_i2c_command")
public func swift_i2c_command(
    _ argc: Int32,
    _ argv: UnsafeMutablePointer<UnsafeMutablePointer<Int8>?>?
) -> Int32 {
    SwiftI2CCommand.run(argc: argc, argv: argv)
}

private enum SwiftI2CCommand {
    static func run(
        argc: Int32,
        argv: UnsafeMutablePointer<UnsafeMutablePointer<Int8>?>?
    ) -> Int32 {
        let args = ShellArguments(argc: argc, argv: argv)
        do {
            try runChecked(args: args)
            return I2CStatus.ok
        } catch {
            writeFailure(error)
            return error.status
        }
    }

    private static func runChecked(args: ShellArguments) throws(CommandFailure) {
        if args.count < 4 {
            throw .usage
        }

        guard let busIndex = args.token(at: 1).parseBusIndex(),
              busIndex <= 31 else {
            throw .invalidBus
        }

        guard let addressValue = args.token(at: 2).parseUInt32(),
              addressValue <= 0x7f else {
            throw .invalidAddress
        }

        let operation = args.token(at: 3)
        let bus = I2CBus(index: busIndex)
        let address = UInt16(addressValue)

        if operation.isWriteKeyword() {
            try runWrite(args: args, bus: bus, address: address)
            return
        }
        if operation.isReadKeyword() {
            try runRead(args: args, bus: bus, address: address)
            return
        }
        if operation.isWriteReadKeyword() {
            try runWriteRead(args: args, bus: bus, address: address)
            return
        }

        throw .unknownOperation
    }

    private static func runWrite(
        args: ShellArguments,
        bus: I2CBus,
        address: UInt16
    ) throws(CommandFailure) {
        if args.count < 5 {
            throw .usage
        }

        bus.resetWriteBuffer()
        try appendWriteBytes(args: args, bus: bus, start: 4, end: args.count)

        let result = bus.transfer(address: address, readCount: 0)
        if !result.isSuccess {
            throw .i2cStatus(result.status)
        }

        Shell.write("ok write ")
        Shell.writeDecimal(UInt32(args.count - 4))
        Shell.write(" byte(s)\n")
    }

    private static func runRead(
        args: ShellArguments,
        bus: I2CBus,
        address: UInt16
    ) throws(CommandFailure) {
        if args.count != 5 {
            throw .usage
        }

        guard let readCount = parseReadCount(args.token(at: 4)) else {
            throw .invalidReadLength
        }

        bus.resetWriteBuffer()
        try transferAndPrintRead(bus: bus, address: address, readCount: readCount)
    }

    private static func runWriteRead(
        args: ShellArguments,
        bus: I2CBus,
        address: UInt16
    ) throws(CommandFailure) {
        var separator: Int32 = 4
        while separator < args.count && !args.token(at: separator).isSeparator() {
            separator += 1
        }

        if separator == 4 || separator + 1 >= args.count || separator + 2 != args.count {
            throw .usage
        }

        guard let readCount = parseReadCount(args.token(at: separator + 1)) else {
            throw .invalidReadLength
        }

        bus.resetWriteBuffer()
        try appendWriteBytes(args: args, bus: bus, start: 4, end: separator)

        try transferAndPrintRead(bus: bus, address: address, readCount: readCount)
    }

    private static func appendWriteBytes(
        args: ShellArguments,
        bus: I2CBus,
        start: Int32,
        end: Int32
    ) throws(CommandFailure) {
        var index = start
        while index < end {
            guard let value = args.token(at: index).parseUInt32(),
                  value <= 0xff else {
                throw .invalidWriteByte
            }

            let status = bus.appendWriteByte(UInt8(value))
            if status != I2CStatus.ok {
                throw .i2cStatus(status)
            }
            index += 1
        }
    }

    private static func parseReadCount(_ token: ShellToken) -> UInt32? {
        guard let readCount = token.parseUInt32(),
              readCount > 0,
              readCount <= 32 else {
            return nil
        }
        return readCount
    }

    private static func transferAndPrintRead(
        bus: I2CBus,
        address: UInt16,
        readCount: UInt32
    ) throws(CommandFailure) {
        let result = bus.transfer(address: address, readCount: readCount)
        if !result.isSuccess {
            throw .i2cStatus(result.status)
        }

        Shell.write("ok read")
        var index: UInt32 = 0
        while index < result.readCount {
            Shell.writeByte(32)
            Shell.writeHex8(bus.readByte(at: index))
            index += 1
        }
        Shell.newline()
    }

    private static func writeFailure(_ failure: CommandFailure) {
        switch failure {
        case .usage:
            writeUsage()
        case .invalidBus:
            Shell.write("invalid i2c bus\n")
            writeUsage()
        case .invalidAddress:
            Shell.write("invalid 7-bit i2c address\n")
            writeUsage()
        case .unknownOperation:
            Shell.write("unknown operation\n")
            writeUsage()
        case .invalidReadLength:
            Shell.write("invalid read length\n")
        case .invalidWriteByte:
            Shell.write("invalid write byte\n")
        case .i2cStatus(let status):
            writeError(status)
        }
    }

    private static func writeError(_ status: Int32) {
        Shell.write("error: ")
        switch status {
        case I2CStatus.invalidArgument:
            Shell.write("invalid argument")
        case I2CStatus.busNotFound:
            Shell.write("i2c bus not found")
        case I2CStatus.bufferOverflow:
            Shell.write("i2c buffer overflow")
        case I2CStatus.transferFailed:
            Shell.write("i2c transfer failed")
        default:
            Shell.write("i2c status ")
            if status < 0 {
                Shell.writeByte(45)
                Shell.writeDecimal(UInt32(-status))
            } else {
                Shell.writeDecimal(UInt32(status))
            }
        }
        Shell.newline()
    }

    private static func writeUsage() {
        Shell.write("usage:\n")
        Shell.write("  swift_i2c <i2cN|N> <addr> w <byte...>\n")
        Shell.write("  swift_i2c <i2cN|N> <addr> r <len>\n")
        Shell.write("  swift_i2c <i2cN|N> <addr> wr <byte...> -- <len>\n")
    }
}

private enum CommandFailure: Error {
    case usage
    case invalidBus
    case invalidAddress
    case unknownOperation
    case invalidReadLength
    case invalidWriteByte
    case i2cStatus(Int32)

    var status: Int32 {
        switch self {
        case .i2cStatus(let status):
            return status
        default:
            return I2CStatus.invalidArgument
        }
    }
}
