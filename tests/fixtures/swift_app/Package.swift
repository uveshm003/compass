// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "SensorGateway",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "gateway", targets: ["Gateway"]),
        .library(name: "Inventory", targets: ["Inventory"]),
    ],
    dependencies: [
        .package(url: "https://github.com/apple/swift-argument-parser.git", from: "1.3.0"),
        .package(
            url: "https://github.com/apple/swift-log.git",
            .upToNextMajor(from: "1.5.0")
        ),
        .package(url: "https://github.com/realm/SwiftLint.git", exact: "0.55.1"),
    ],
    targets: [
        .target(
            name: "Inventory",
            dependencies: [.product(name: "Logging", package: "swift-log")]
        ),
        .executableTarget(
            name: "Gateway",
            dependencies: [
                "Inventory",
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
            ]
        ),
        .testTarget(name: "InventoryTests", dependencies: ["Inventory"]),
    ]
)
