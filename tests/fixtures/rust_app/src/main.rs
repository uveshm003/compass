use sensor_gateway::transport::retry::Backoff;

fn main() {
    let backoff = Backoff::default();
    println!("{:?}", backoff);
}
