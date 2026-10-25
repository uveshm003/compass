// The gateway: reads sensors once, then uploads what it collected.
import ArgumentParser
import Inventory

struct Gateway: AsyncParsableCommand {
    @Option(help: "Sensor serial number.")
    var sensor = "s1"

    func run() async throws {
        let store = MemoryStore()
        try store.save(Reading(sensorId: sensor, ppm: 52.0))
        let sent = await Uploader(store: store).flush { reading in
            print(reading)
        }
        print("sent \(sent)")
    }
}

await Gateway.main()
