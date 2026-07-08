// swift-tools-version: 6.1
import PackageDescription

let embeddedSwiftSettings: [SwiftSetting] = [
    .swiftLanguageMode(.v5),
    .enableExperimentalFeature("Embedded"),
]

let package = Package(
    name: "Rk3568AmpUart7RttDemo",
    products: [
        .library(
            name: "AmpLogic",
            type: .static,
            targets: ["AmpLogic"]
        )
    ],
    targets: [
        .target(
            name: "RtThreadShell",
            swiftSettings: embeddedSwiftSettings
        ),
        .target(
            name: "RtThreadI2C",
            swiftSettings: embeddedSwiftSettings
        ),
        .target(
            name: "AmpLogic",
            dependencies: ["RtThreadI2C", "RtThreadShell"],
            swiftSettings: embeddedSwiftSettings
        )
    ]
)
