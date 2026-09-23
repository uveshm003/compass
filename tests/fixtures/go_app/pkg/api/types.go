package api

// Frame is one message from a device.
type Frame struct {
	DeviceID string `json:"device_id"`
	PPM      float64
}

// Handler processes frames.
type Handler func(Frame) error

type ID = string
