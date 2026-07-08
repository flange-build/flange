// swift-tools-version: 6.1
import PackageDescription

let package = Package(
    name: "${name_ident}Package",
    products: [
        .library(
            name: "AmpLogic",
            type: .static,
            targets: ["AmpLogic"]
        )
    ],
    targets: [
        .target(
            name: "AmpLogic",
            swiftSettings: [
                .swiftLanguageMode(.v5),
                .enableExperimentalFeature("Embedded"),
            ]
        )
    ]
)
