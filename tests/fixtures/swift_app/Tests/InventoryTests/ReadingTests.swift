import XCTest
@testable import Inventory

final class ReadingTests: XCTestCase {
    func testAlarm() {
        XCTAssertTrue(Reading(sensorId: "s1", ppm: 50.0).isAlarm())
        XCTAssertFalse(Reading(sensorId: "s1", ppm: 10.0).isAlarm())
    }

    func testSeverity() {
        XCTAssertEqual(Reading(sensorId: "s1", ppm: 250.0).severity(), .critical)
    }

    func testStoreKeepsReadings() throws {
        let store = MemoryStore()
        try store.save(Reading(sensorId: "s2", ppm: 5.0))
        XCTAssertEqual(store.pending().count, 1)
    }
}
