// Command sensord runs the sensor gateway.
package main

import (
	"log"

	"github.com/example/sensord/internal/transport"
)

func main() {
	if err := transport.Retry(func() error { return nil }, &transport.Exponential{}); err != nil {
		log.Fatal(err)
	}
}
