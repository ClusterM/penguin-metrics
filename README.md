# Penguin Metrics

Linux system telemetry service for Home Assistant via MQTT.

## Features

- **System Metrics**: CPU, RAM, swap, load average, uptime
- **Temperature**: Thermal zones from `/sys/class/thermal/`
- **Process Monitoring**: By name, regex pattern, PID, or pidfile
- **Memory Details**: PSS/USS via `/proc/PID/smaps` (requires root)
- **Systemd Services**: State, CPU, memory via cgroups
- **Docker Containers**: CPU, memory, network, disk I/O
- **Battery**: Capacity, status, voltage, current, health
- **Custom Sensors**: Run shell commands or scripts
- **GPU**: Basic metrics via sysfs (frequency, temperature)

## Requirements

- Python 3.11+
- Linux with `/proc` and `/sys` filesystems
- MQTT broker (Mosquitto, EMQX, etc.)
- Home Assistant with MQTT integration (optional)

## Installation

### From source

```bash
# Clone repository
cd /opt
git clone https://github.com/clusterm/penguin-metrics.git
cd penguin-metrics

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and edit configuration
cp config.example.conf /etc/penguin-metrics/config.conf
nano /etc/penguin-metrics/config.conf
```

### As systemd service

```bash
# Copy service file
sudo cp penguin-metrics.service /etc/systemd/system/

# Create config directory
sudo mkdir -p /etc/penguin-metrics
sudo cp config.example.conf /etc/penguin-metrics/config.conf

# Edit configuration
sudo nano /etc/penguin-metrics/config.conf

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable penguin-metrics
sudo systemctl start penguin-metrics

# Check status
sudo systemctl status penguin-metrics
sudo journalctl -u penguin-metrics -f
```

### With Docker

```bash
# Build image
docker build -t penguin-metrics .

# Run with docker-compose
docker-compose up -d

# Or run directly
docker run -d \
  --name penguin-metrics \
  --privileged \
  --pid=host \
  -v /proc:/host/proc:ro \
  -v /sys:/host/sys:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v ./config.conf:/etc/penguin-metrics/config.conf:ro \
  --network=host \
  penguin-metrics
```

## Usage

### Command Line

```bash
# Validate configuration
python -m penguin_metrics --validate /path/to/config.conf

# Run with verbose logging
python -m penguin_metrics -v /path/to/config.conf

# Run with debug logging
python -m penguin_metrics -d /path/to/config.conf

# Show version
python -m penguin_metrics --version

# Show help
python -m penguin_metrics --help
```

### Configuration Validation

```bash
$ python -m penguin_metrics --validate config.conf

Configuration summary:
  MQTT: 10.13.1.100:1833
  Home Assistant Discovery: enabled
  System collectors: 1
  Process monitors: 2
  Service monitors: 1
  Container monitors: 1
  Battery monitors: 0
  Custom sensors: 1

Configuration is valid!
```

## Configuration

Penguin Metrics uses an nginx-like configuration syntax with blocks and directives.

### Basic Structure

```nginx
# Comments start with #

block_type "optional_name" {
    directive value;
    directive value1 value2;
    
    nested_block {
        directive value;
    }
}

# Include other config files
include "/etc/penguin-metrics/conf.d/*.conf";
```

### MQTT Configuration

```nginx
mqtt {
    host "localhost";          # MQTT broker address
    port 1883;                 # MQTT broker port
    username "user";           # Optional: username
    password "pass";           # Optional: password
    client_id "penguin";       # Optional: client ID (auto-generated if not set)
    topic_prefix "penguin_metrics";  # Base topic for all messages
    qos 1;                     # QoS level (0, 1, 2)
    retain on;                 # Retain messages
    keepalive 60;              # Keepalive interval in seconds
}
```

**Default values:**
| Directive | Default | Description |
|-----------|---------|-------------|
| `host` | `"localhost"` | MQTT broker address |
| `port` | `1883` | MQTT broker port |
| `username` | *(none)* | Authentication username |
| `password` | *(none)* | Authentication password |
| `client_id` | *(auto-generated)* | MQTT client identifier |
| `topic_prefix` | `"penguin_metrics"` | Base topic for all messages |
| `qos` | `1` | Quality of Service (0, 1, 2) |
| `retain` | `on` | Retain messages on broker |
| `keepalive` | `60` | Keepalive interval (seconds) |

### Home Assistant Integration

```nginx
homeassistant {
    discovery on;              # Enable MQTT Discovery
    discovery_prefix "homeassistant";  # Discovery topic prefix
    
    # Device grouping:
    # - per_source: separate device per process/service/container
    # - single: all sensors in one device
    # - hybrid: system in one, others separate
    device_grouping per_source;
    
    # Default device info
    device {
        manufacturer "Penguin Metrics";
        model "Linux Monitor";
    }
}
```

**Default values:**
| Directive | Default | Description |
|-----------|---------|-------------|
| `discovery` | `on` | Enable MQTT Discovery |
| `discovery_prefix` | `"homeassistant"` | Discovery topic prefix |
| `device_grouping` | `per_source` | Grouping strategy |
| `device.manufacturer` | `"Penguin Metrics"` | Device manufacturer |
| `device.model` | `"Linux Monitor"` | Device model |

### Default Settings

```nginx
defaults {
    update_interval 10s;       # Collection interval (supports: ms, s, m, h, d)
    smaps off;                 # PSS/USS memory metrics (requires root)
    availability_topic on;     # Publish online/offline status
}
```

**Default values:**
| Directive | Default | Description |
|-----------|---------|-------------|
| `update_interval` | `10s` | Collection interval |
| `smaps` | `off` | PSS/USS memory (requires root) |
| `availability_topic` | `on` | Publish online/offline status |

**Duration formats:** `ms` (milliseconds), `s` (seconds), `m` (minutes), `h` (hours), `d` (days)

### System Metrics

```nginx
system "server-name" {
    id "custom_id";            # Optional: custom ID for topics
    
    cpu on;                    # Total CPU usage
    cpu_per_core off;          # Per-core CPU usage
    memory on;                 # Memory usage
    swap on;                   # Swap usage
    load on;                   # Load average (1, 5, 15 min)
    uptime on;                 # System uptime
    temperature on;            # Thermal zones
    gpu off;                   # GPU metrics (if available)
    
    update_interval 5s;
    
    device {
        name "My Server";
        manufacturer "Dell";
        model "PowerEdge R740";
    }
}
```

**Default values:**
| Directive | Default | Description |
|-----------|---------|-------------|
| `id` | *(from name)* | Custom ID for topics |
| `cpu` | `on` | Total CPU usage |
| `cpu_per_core` | `off` | Per-core CPU usage |
| `memory` | `on` | Memory usage |
| `swap` | `on` | Swap usage |
| `load` | `on` | Load average |
| `uptime` | `on` | System uptime |
| `temperature` | `on` | Thermal zones |
| `gpu` | `off` | GPU metrics |
| `update_interval` | *(from defaults)* | Override default interval |

### Process Monitoring

```nginx
# Match by exact process name
process "docker" {
    match name "dockerd";
    
    cpu on;
    memory on;
    smaps on;                  # PSS/USS (requires root)
    io on;                     # I/O bytes
    fds on;                    # Open file descriptors
    threads on;                # Thread count
}

# Match by regex pattern
process "nginx-workers" {
    match pattern "nginx: worker.*";
    aggregate on;              # Sum metrics from all matches
    
    cpu on;
    memory on;
}

# Match by PID file
process "my-app" {
    match pidfile "/var/run/my-app.pid";
    
    cpu on;
    memory on;
}

# Match by command line substring
process "python-script" {
    match cmdline "/opt/scripts/main.py";
    
    cpu on;
    memory on;
}
```

**Default values:**
| Directive | Default | Description |
|-----------|---------|-------------|
| `cpu` | `on` | CPU usage |
| `memory` | `on` | Memory (RSS) |
| `smaps` | *(from defaults)* | PSS/USS memory |
| `io` | `off` | I/O bytes read/write |
| `fds` | `off` | Open file descriptors |
| `threads` | `off` | Thread count |
| `aggregate` | `off` | Sum metrics from all matches |
| `update_interval` | *(from defaults)* | Override default interval |

**Match types:**
| Type | Example | Description |
|------|---------|-------------|
| `name` | `match name "nginx";` | Exact process name (comm) |
| `pattern` | `match pattern "nginx:.*";` | Regex on command line |
| `pid` | `match pid 1234;` | Exact PID |
| `pidfile` | `match pidfile "/var/run/app.pid";` | Read PID from file |
| `cmdline` | `match cmdline "/usr/bin/app";` | Substring in command line |

### Systemd Service Monitoring

```nginx
service "docker" {
    match unit "docker.service";
    
    cpu on;                    # CPU time from cgroup
    memory on;                 # Memory from cgroup
    smaps on;                  # PSS/USS aggregated
    state on;                  # active/inactive/failed
    restart_count on;          # Number of restarts
}

# Match by pattern
service "nginx" {
    match pattern "nginx*.service";
    
    cpu on;
    memory on;
    state on;
}
```

**Default values:**
| Directive | Default | Description |
|-----------|---------|-------------|
| `cpu` | `on` | CPU time from cgroup |
| `memory` | `on` | Memory from cgroup |
| `smaps` | *(from defaults)* | PSS/USS aggregated |
| `state` | `on` | Service state |
| `restart_count` | `off` | Number of restarts |
| `update_interval` | *(from defaults)* | Override default interval |

**Match types:**
| Type | Example | Description |
|------|---------|-------------|
| `unit` | `match unit "docker.service";` | Exact unit name |
| `pattern` | `match pattern "nginx*.service";` | Glob pattern |

### Docker Container Monitoring

```nginx
container "homeassistant" {
    match name "homeassistant";
    
    cpu on;                    # CPU usage %
    memory on;                 # Memory usage
    network on;                # Network RX/TX
    disk on;                   # Block I/O
    state on;                  # running/exited/etc
    health on;                 # Healthcheck status
    uptime on;                 # Container uptime
}

# Match by image
container "postgres" {
    match image "postgres:";
    
    cpu on;
    memory on;
    state on;
}

# Match by label
container "monitored" {
    match label "metrics.enabled=true";
    
    cpu on;
    memory on;
}
```

**Default values:**
| Directive | Default | Description |
|-----------|---------|-------------|
| `cpu` | `on` | CPU usage % |
| `memory` | `on` | Memory usage |
| `network` | `off` | Network RX/TX bytes |
| `disk` | `off` | Block I/O |
| `state` | `on` | Container state |
| `health` | `off` | Healthcheck status |
| `uptime` | `off` | Container uptime |
| `auto_discover` | `off` | Create device per matched container |
| `update_interval` | *(from defaults)* | Override default interval |

**Match types:**
| Type | Example | Description |
|------|---------|-------------|
| `name` | `match name "nginx";` | Exact container name |
| `pattern` | `match pattern "web-.*";` | Regex on name |
| `image` | `match image "postgres:";` | Image name (substring) |
| `label` | `match label "app=web";` | Container label |

### Battery Monitoring

```nginx
battery "main" {
    # Auto-detect first battery, or specify:
    # path "/sys/class/power_supply/BAT0";
    # name "BAT0";
    
    capacity on;               # Charge percentage
    status on;                 # Charging/Discharging/Full
    voltage on;                # Current voltage
    current on;                # Current amperage
    power on;                  # Power consumption
    health on;                 # Battery health
    cycles on;                 # Charge cycles
    temperature on;            # Battery temperature
    time_to_empty on;          # Estimated time remaining
    time_to_full on;           # Time to full charge
    
    update_interval 30s;
}
```

**Default values:**
| Directive | Default | Description |
|-----------|---------|-------------|
| `path` | *(auto-detect)* | Path to battery in sysfs |
| `name` | *(auto-detect)* | Battery name (BAT0, etc.) |
| `capacity` | `on` | Charge percentage |
| `status` | `on` | Charging/Discharging/Full |
| `voltage` | `off` | Current voltage |
| `current` | `off` | Current amperage |
| `power` | `off` | Power consumption |
| `health` | `off` | Battery health |
| `cycles` | `off` | Charge cycle count |
| `temperature` | `off` | Battery temperature |
| `time_to_empty` | `off` | Time remaining |
| `time_to_full` | `off` | Time to full charge |
| `update_interval` | *(from defaults)* | Override default interval |

### Custom Sensors

```nginx
# Read from command output
custom "room_temp" {
    command "cat /sys/bus/w1/devices/28-*/temperature";
    
    type number;               # number, string, json
    unit "°C";
    scale 0.001;               # Multiply result
    
    device_class temperature;
    state_class measurement;
    
    update_interval 30s;
    timeout 5s;
}

# Run script
custom "disk_health" {
    script "/opt/scripts/check_smart.sh";
    type string;
    update_interval 1h;
}

# Get external IP
custom "wan_ip" {
    command "curl -s ifconfig.me";
    type string;
    update_interval 5m;
}
```

**Default values:**
| Directive | Default | Description |
|-----------|---------|-------------|
| `command` | *(required)* | Shell command to execute |
| `script` | *(none)* | Script path (alternative to command) |
| `type` | `"number"` | Output type: `number`, `string`, `json` |
| `unit` | *(none)* | Unit of measurement |
| `scale` | `1.0` | Multiply numeric result by this |
| `device_class` | *(none)* | HA device class |
| `state_class` | *(none)* | HA state class |
| `timeout` | `5s` | Command timeout |
| `update_interval` | *(from defaults)* | Override default interval |

**Output types:**
| Type | Description |
|------|-------------|
| `number` | Parse as float, apply `scale` |
| `string` | Use raw output as-is |
| `json` | Parse as JSON object |

### Temperature Zones (Standalone)

```nginx
temperature "cpu" {
    zone "cpu-thermal";        # Thermal zone name
    # Or: path "/sys/class/thermal/thermal_zone0/temp";
    
    warning 70;
    critical 85;
}
```

### Include Files

```nginx
# Include single file
include "/etc/penguin-metrics/processes.conf";

# Include with glob pattern
include "/etc/penguin-metrics/conf.d/*.conf";
```

## MQTT Topics

### State Topics

Sensor values are published to:
```
{topic_prefix}/{source_id}/{metric_name}
```

Example:
```
penguin_metrics/main/cpu_percent         -> 45.2
penguin_metrics/main/memory_percent      -> 67.8
penguin_metrics/docker/cpu_percent       -> 2.5
penguin_metrics/docker/state             -> running
```

### Availability Topics

Device availability:
```
{topic_prefix}/{device_id}/status        -> online/offline
{topic_prefix}/status                    -> online/offline (main)
```

### Home Assistant Discovery

Discovery messages are published to:
```
homeassistant/sensor/{unique_id}/config
```

## Permissions

### For smaps (PSS/USS memory)

Reading `/proc/PID/smaps` of other processes requires:
- Running as root, OR
- `CAP_SYS_PTRACE` capability

```bash
# Grant capability
sudo setcap cap_sys_ptrace+ep /path/to/.venv/bin/python3
```

### For Docker monitoring

Access to Docker socket:
```bash
# Add user to docker group
sudo usermod -aG docker penguin-metrics

# Or run as root
```

### For cgroup metrics

Reading cgroup files usually works without special permissions.

## Troubleshooting

### Connection Refused

```
ERROR: Failed to connect to MQTT: [Errno 111] Connection refused
```

- Check MQTT broker is running
- Verify host/port in configuration
- Check firewall rules

### Permission Denied

```
WARNING: Cannot read /proc/1234/smaps: Permission denied
```

- Run as root for smaps access
- Or disable smaps in config: `smaps off;`

### No sensors in Home Assistant

1. Check MQTT broker connection
2. Verify `discovery on;` in config
3. Check Home Assistant MQTT integration
4. Look for discovery messages:
   ```bash
   mosquitto_sub -h localhost -t "homeassistant/#" -v
   ```

### Process not found

```
WARNING: Collector docker unavailable: No sources found
```

- Verify process is running: `pgrep -a dockerd`
- Check match configuration
- For patterns, test regex: `pgrep -f "pattern"`

### Docker socket not available

```
ERROR: Docker socket not available
```

- Check socket exists: `ls -la /var/run/docker.sock`
- Check permissions
- If running in container, mount the socket

## Testing

### Test configuration

```bash
python -m penguin_metrics --validate config.conf
```

### Test MQTT connection

```bash
# Subscribe to all topics
mosquitto_sub -h 10.13.1.100 -p 1833 \
  -u penguin_metrics -P password \
  -t "penguin_metrics/#" -v

# In another terminal, run the service
python -m penguin_metrics -v config.conf
```

### Test Home Assistant Discovery

```bash
# Subscribe to discovery topics
mosquitto_sub -h 10.13.1.100 -p 1833 \
  -u penguin_metrics -P password \
  -t "homeassistant/sensor/#" -v
```

### Test individual collectors

```python
import asyncio
from penguin_metrics.collectors.system import SystemCollector
from penguin_metrics.config.schema import SystemConfig, DefaultsConfig

async def test():
    config = SystemConfig(name="test")
    defaults = DefaultsConfig()
    
    collector = SystemCollector(config, defaults)
    await collector.initialize()
    
    result = await collector.collect()
    for metric in result.metrics:
        print(f"{metric.sensor_id}: {metric.value}")

asyncio.run(test())
```

## Development

### Running tests

```bash
# Install dev dependencies
pip install pytest pytest-asyncio

# Run tests
pytest tests/
```

### Code structure

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed code documentation.

## License

MIT License

