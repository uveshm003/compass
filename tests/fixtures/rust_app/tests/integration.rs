use sensor_gateway::Reading;

#[test]
fn reading_display() {
    assert_eq!(Reading::new("s1", 2.0).to_string(), "s1=2");
}
