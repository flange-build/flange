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
