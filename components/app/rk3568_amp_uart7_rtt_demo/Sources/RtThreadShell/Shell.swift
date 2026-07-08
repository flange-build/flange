@_silgen_name("rt_kputs")
private func rt_kputs(_ text: UnsafePointer<CChar>?)

public enum Shell {
    public static func write(_ text: StaticString) {
        let count = text.utf8CodeUnitCount
        var index = 0
        while index < count {
            writeByte(text.utf8Start[index])
            index += 1
        }
    }

    public static func writeByte(_ byte: UInt8) {
        var buffer = (Int8(bitPattern: byte), Int8(0))
        withUnsafePointer(to: &buffer) { pointer in
            pointer.withMemoryRebound(to: CChar.self, capacity: 2) {
                rt_kputs($0)
            }
        }
    }

    public static func newline() {
        writeByte(10)
    }

    public static func writeHex8(_ value: UInt8) {
        writeByte(hexDigit((value >> 4) & 0x0f))
        writeByte(hexDigit(value & 0x0f))
    }

    public static func writeHex16(_ value: UInt16) {
        writeHex8(UInt8((value >> 8) & 0x00ff))
        writeHex8(UInt8(value & 0x00ff))
    }

    public static func writeDecimal(_ value: UInt32) {
        if value == 0 {
            writeByte(48)
            return
        }

        var divisor: UInt32 = 1
        while divisor <= value / 10 {
            divisor *= 10
        }

        var remaining = value
        while divisor > 0 {
            let digit = remaining / divisor
            writeByte(UInt8(48 + digit))
            remaining %= divisor
            divisor /= 10
        }
    }

    private static func hexDigit(_ value: UInt8) -> UInt8 {
        if value < 10 {
            return 48 + value
        }
        return 87 + value
    }
}

public struct ShellArguments {
    private let argc: Int32
    private let argv: UnsafeMutablePointer<UnsafeMutablePointer<Int8>?>?

    public init(
        argc: Int32,
        argv: UnsafeMutablePointer<UnsafeMutablePointer<Int8>?>?
    ) {
        self.argc = argc
        self.argv = argv
    }

    public var count: Int32 {
        argc
    }

    public func token(at index: Int32) -> ShellToken {
        if index < 0 || index >= argc {
            return ShellToken(pointer: nil)
        }
        guard let argv = argv else {
            return ShellToken(pointer: nil)
        }
        return ShellToken(pointer: argv[Int(index)])
    }
}

public struct ShellToken {
    private let pointer: UnsafeMutablePointer<Int8>?

    public init(pointer: UnsafeMutablePointer<Int8>?) {
        self.pointer = pointer
    }

    public var isValid: Bool {
        pointer != nil
    }

    public func isReadKeyword() -> Bool {
        equals1(114) || equals4(114, 101, 97, 100)
    }

    public func isWriteKeyword() -> Bool {
        equals1(119) || equals5(119, 114, 105, 116, 101)
    }

    public func isWriteReadKeyword() -> Bool {
        equals2(119, 114) || equals9(119, 114, 105, 116, 101, 114, 101, 97, 100)
    }

    public func isSeparator() -> Bool {
        equals2(45, 45)
    }

    public func parseBusIndex() -> UInt32? {
        if hasI2CPrefix() {
            return parseUInt32(from: 3)
        }
        return parseUInt32(from: 0)
    }

    public func parseUInt32() -> UInt32? {
        parseUInt32(from: 0)
    }

    private func parseUInt32(from start: Int) -> UInt32? {
        guard let pointer = pointer else {
            return nil
        }

        var index = start
        var base: UInt32 = 10
        if byte(at: index, pointer: pointer) == 48 &&
            (byte(at: index + 1, pointer: pointer) == 120 ||
             byte(at: index + 1, pointer: pointer) == 88) {
            base = 16
            index += 2
        }

        var value: UInt32 = 0
        var hasDigit = false
        while true {
            let current = byte(at: index, pointer: pointer)
            if current == 0 {
                break
            }
            guard let digit = digitValue(current), digit < base else {
                return nil
            }
            if value > (UInt32.max - digit) / base {
                return nil
            }
            value = value * base + digit
            hasDigit = true
            index += 1
        }

        return hasDigit ? value : nil
    }

    private func hasI2CPrefix() -> Bool {
        guard let pointer = pointer else {
            return false
        }
        return byte(at: 0, pointer: pointer) == 105 &&
            byte(at: 1, pointer: pointer) == 50 &&
            byte(at: 2, pointer: pointer) == 99
    }

    private func equals1(_ b0: UInt8) -> Bool {
        guard let pointer = pointer else {
            return false
        }
        return byte(at: 0, pointer: pointer) == b0 &&
            byte(at: 1, pointer: pointer) == 0
    }

    private func equals2(_ b0: UInt8, _ b1: UInt8) -> Bool {
        guard let pointer = pointer else {
            return false
        }
        return byte(at: 0, pointer: pointer) == b0 &&
            byte(at: 1, pointer: pointer) == b1 &&
            byte(at: 2, pointer: pointer) == 0
    }

    private func equals4(_ b0: UInt8, _ b1: UInt8, _ b2: UInt8, _ b3: UInt8) -> Bool {
        guard let pointer = pointer else {
            return false
        }
        return byte(at: 0, pointer: pointer) == b0 &&
            byte(at: 1, pointer: pointer) == b1 &&
            byte(at: 2, pointer: pointer) == b2 &&
            byte(at: 3, pointer: pointer) == b3 &&
            byte(at: 4, pointer: pointer) == 0
    }

    private func equals5(
        _ b0: UInt8,
        _ b1: UInt8,
        _ b2: UInt8,
        _ b3: UInt8,
        _ b4: UInt8
    ) -> Bool {
        guard let pointer = pointer else {
            return false
        }
        return byte(at: 0, pointer: pointer) == b0 &&
            byte(at: 1, pointer: pointer) == b1 &&
            byte(at: 2, pointer: pointer) == b2 &&
            byte(at: 3, pointer: pointer) == b3 &&
            byte(at: 4, pointer: pointer) == b4 &&
            byte(at: 5, pointer: pointer) == 0
    }

    private func equals9(
        _ b0: UInt8,
        _ b1: UInt8,
        _ b2: UInt8,
        _ b3: UInt8,
        _ b4: UInt8,
        _ b5: UInt8,
        _ b6: UInt8,
        _ b7: UInt8,
        _ b8: UInt8
    ) -> Bool {
        guard let pointer = pointer else {
            return false
        }
        return byte(at: 0, pointer: pointer) == b0 &&
            byte(at: 1, pointer: pointer) == b1 &&
            byte(at: 2, pointer: pointer) == b2 &&
            byte(at: 3, pointer: pointer) == b3 &&
            byte(at: 4, pointer: pointer) == b4 &&
            byte(at: 5, pointer: pointer) == b5 &&
            byte(at: 6, pointer: pointer) == b6 &&
            byte(at: 7, pointer: pointer) == b7 &&
            byte(at: 8, pointer: pointer) == b8 &&
            byte(at: 9, pointer: pointer) == 0
    }

    private func byte(at offset: Int, pointer: UnsafeMutablePointer<Int8>) -> UInt8 {
        UInt8(bitPattern: pointer[offset])
    }

    private func digitValue(_ byte: UInt8) -> UInt32? {
        if byte >= 48 && byte <= 57 {
            return UInt32(byte - 48)
        }
        if byte >= 65 && byte <= 70 {
            return UInt32(byte - 55)
        }
        if byte >= 97 && byte <= 102 {
            return UInt32(byte - 87)
        }
        return nil
    }
}
