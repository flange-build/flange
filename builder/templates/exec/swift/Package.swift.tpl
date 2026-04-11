// swift-tools-version:5.7
import PackageDescription

// ${description}
let package = Package(
    name: "${name}",
    targets: [
        .executableTarget(
            name: "${name}",
            path: "Sources"
        ),
    ]
)
