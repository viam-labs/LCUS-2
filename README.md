# LCUS-2

Viam driver for the [LCUS-2](http://www.chinalctech.com/cpzx/Programmer/Relay_Module/115.html) two-channel USB relay. The board is a CH340 serial port at 9600 8N1. This module runs on macOS and Linux and exposes each coil as a [switch](https://docs.viam.com/components/switch/).

| Position | Label | Coil |
| --- | --- | --- |
| 0 | off | released |
| 1 | on | energized |

Add one switch per channel. Both switches share a single open serial port.

## Configuration

| Attribute | Required | Description |
| --- | --- | --- |
| `channel` | yes | `1` or `2`. |
| `serial_path` | no | Device node. When omitted, the module uses the only attached CH340. If several are attached, it uses the one that answers an LCUS-2 status query. |
| `baud_rate` | no | Defaults to `9600`. |

Find the node with `ls /dev/cu.wchusbserial* /dev/cu.usbserial*` on macOS, or `ls /dev/ttyUSB*` on Linux. On macOS, open the `cu` device. If the board does not appear, install the WCH CH340 driver. On Linux, the `ch341` kernel module is usually enough; if open fails with a permission error, add your user to `dialout` and log in again (`sudo usermod -aG dialout $USER`).

```json
{
  "modules": [
    {
      "type": "local",
      "name": "lcus-2",
      "executable_path": "/absolute/path/to/LCUS-2/run.sh"
    }
  ],
  "components": [
    {
      "name": "relay-1",
      "namespace": "rdk",
      "type": "switch",
      "model": "viam-labs:lcus-2:relay",
      "attributes": {
        "channel": 1,
        "serial_path": "/dev/cu.wchusbserial110"
      }
    },
    {
      "name": "relay-2",
      "namespace": "rdk",
      "type": "switch",
      "model": "viam-labs:lcus-2:relay",
      "attributes": {
        "channel": 2,
        "serial_path": "/dev/cu.wchusbserial110"
      }
    }
  ]
}
```

Use the same `serial_path` string for both components, or omit it on both when only one CH340 is plugged in. On Linux, omitting it also works when other CH340 devices are present, as long as one of them answers an LCUS-2 status query. A registry install uses module id `viam-labs:lcus-2` in place of `executable_path`.

```python
relay = Switch.from_robot(machine, "relay-1")
await relay.set_position(1)  # on
await relay.set_position(0)  # off
print(await relay.get_position())
```

`DoCommand` can address either coil from one component:

```json
{"command": "on"}
{"command": "off"}
{"command": "status"}
{"command": "set", "channel": 2, "on": true}
```

`status` reads both coils when the board answers a query.

## Run from this repo

```sh
./setup.sh
```

Point a machine at `run.sh` as a local module. `viam-server` passes its socket path through to the process.

```sh
make test
./device.sh  # hold each channel on for 1 second, then turn it off
./build.sh   # writes dist/archive.tar.gz
```

`./device.sh` finds the LCUS-2 and holds each channel on for 1 second. `./device.sh 5` holds each for 5 seconds. `./device.sh 2 4` holds channel 1 for 2 seconds and channel 2 for 4. `./device.sh --status` only reads. Pass `--path` or `--channel` when more than one board or coil is attached.

On macOS, Apple's CH340 driver often leaves the board silent after the process that opened the port exits. Unplug the board and plug it back in. The module keeps the port open while `viam-server` is running, so this shows up when that process exits and when `./device.sh` is run again. The Linux `ch341` driver keeps working across open and close.

Running from this repo works on Intel and Apple Silicon Macs and on Linux. Registry builds are published for `linux/amd64`, `linux/arm64`, and `darwin/arm64`.

## Protocol

Commands are four raw bytes. The fourth byte is the low eight bits of the sum of the first three. `0xFF` asks for both coil states; the reply looks like `CH1: ON\r\nCH2: OFF\r\n`.

| Action | Bytes |
| --- | --- |
| Channel 1 on | `A0 01 01 A2` |
| Channel 1 off | `A0 01 00 A1` |
| Channel 2 on | `A0 02 01 A3` |
| Channel 2 off | `A0 02 00 A2` |
| Query | `FF` |

Opening the port keeps DTR and RTS low so connecting does not pulse the coils. If a clone ignores `FF`, the driver asks each channel with operation `0x02` (`A0 01 02 A3`, `A0 02 02 A4`). If the board never answers, later reads report the last commanded state.
