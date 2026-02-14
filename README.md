# Penguin Metrics

[![Tests](https://github.com/clusterm/penguin-metrics/actions/workflows/test.yml/badge.svg)](https://github.com/clusterm/penguin-metrics/actions/workflows/test.yml)

Linux system telemetry service that sends data to MQTT, with Home Assistant integration via MQTT Discovery.

**Why monitor your servers through Home Assistant?**

- 📊 **All in one place** — see your servers alongside smart home devices in a single dashboard
- 🪶 **Lightweight** — no need for heavy monitoring stacks like Prometheus + Grafana
- 🔔 **Smart automations** — get notifications when disk space is low, CPU is overloaded, or a service goes down
- 📈 **Beautiful visualization** — Home Assistant offers flexible cards, graphs, and history tracking
- 🔌 **Zero configuration on HA side** — MQTT Discovery automatically creates all sensors and devices
- 🏠 **Perfect for home servers** — simple setup, minimal resource usage, native HA integration

## Features

### Data Collection
- **System Metrics**: CPU (overall and per-core), RAM, swap, load average, uptime, disk I/O (bytes + KiB/s rate), CPU frequency (MHz), process count, boot time
- **Temperature**: Thermal zones and hwmon sensors (auto-discovery supported)
- **Disk Space**: Total, used, free space and usage percentage (auto-discovery supported)
- **Process Monitoring**: By name, regex pattern, PID, or pidfile
- **Memory Details**: 
  - Standard RSS (Resident Set Size)
  - PSS/USS via `/proc/PID/smaps` (requires root or `CAP_SYS_PTRACE`)
  - **Real PSS/USS**: Excludes file-backed mappings (accurate for apps that map large files)
- **Systemd Services**: State, CPU, memory via cgroups (auto-discovery with filter)
- **Docker Containers**: CPU, memory, network, disk I/O with optional rate metrics (KiB/s)
- **Battery**: Capacity, status, voltage, current, health (auto-discovery supported)
- **AC Power**: External power supply presence (`online`/`offline`, with auto-discovery)
- **Network Interfaces**: Bytes, packets, errors, drops, rate, isup, speed, mtu, duplex, optional Wi-Fi RSSI (dBm) (auto-discovery supported)
- **Fan (RPM)**: hwmon fan*_input from sysfs (auto-discovery supported)
- **Custom Sensors**: Run shell commands or scripts
- **Binary Sensors**: ON/OFF states from command execution (e.g., ping checks)
- **GPU**: Basic metrics via sysfs (frequency, temperature) - minimal implementation

### MQTT Integration
- **JSON Payloads**: Single topic per source with all metrics in JSON format
- **Retain Modes**: `on` (retain all) or `off` (no retention)
- **Availability**: Dual availability system (global app status + local source state)
- **Last Will and Testament**: Automatic offline notification on disconnect

### Home Assistant Integration
- **MQTT Discovery**: Automatic sensor and device registration
- **Device Templates**: Define reusable device configurations with custom grouping
- **Flexible Device Assignment**: Use `system`, `auto`, `none`, or templates for each sensor
- **Value Templates**: Extract metrics from JSON payloads
- **Stale Sensor Cleanup**: Removed sensors are automatically cleaned from Home Assistant

### Auto-Discovery
- **Temperature Sensors**: Automatic detection with filter/exclude patterns
- **Disk Partitions**: Auto-discovery of mounted block devices
- **Batteries**: Auto-discovery of all power supplies
- **AC Power Supplies**: Auto-discovery of non-battery power sources under `/sys/class/power_supply`
- **Network Interfaces**: Auto-discovery of interfaces (filter/exclude by name, e.g. eth*, wlan*)
- **Docker Containers**: Auto-discovery with name/image/label filters
- **Systemd Services**: Auto-discovery with required filter (safety)
- **Processes**: Auto-discovery with required filter (safety)
- **Dynamic Refresh**: Periodic check for new/removed sources (configurable interval)

## Requirements

- Python 3.11+
- Linux with `/proc` and `/sys` filesystems
- MQTT broker (Mosquitto, EMQX, etc.)
- Home Assistant with MQTT integration (optional)
- Root or `CAP_SYS_PTRACE` capability (for smaps memory metrics)

## Installation

### From source (development)

```bash
# Clone repository
cd /opt
git clone https://github.com/clusterm/penguin-metrics.git
cd penguin-metrics

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in development mode (editable)
pip install -e .

# Or install with dev dependencies
pip install -e ".[dev]"

# Copy and edit configuration
sudo mkdir -p /etc/penguin-metrics
sudo cp config.example.conf /etc/penguin-metrics/config.conf
sudo nano /etc/penguin-metrics/config.conf
```

### Install as package

```bash
# Build wheel
pip install build
python -m build

# Install built package
pip install dist/penguin_metrics-0.0.1-py3-none-any.whl

# Or install directly from source
pip install .
```

### Using pip from git

```bash
pip install git+https://github.com/clusterm/penguin-metrics.git
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
  AC power monitors: 0
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

### Common Directives

All collector blocks support these directives:

| Directive | Default | Description |
|-----------|---------|-------------|
| `display_name` | *(block name)* | Human-readable name for Home Assistant sensors. Does not affect topics or IDs |
| `device` | *(varies)* | Device grouping: `system`, `auto`, `none`, or a template name |
| `update_interval` | *(from defaults)* | Override the collection interval for this block |

**Example** — `display_name` overrides only the display name in HA:

```nginx
disk "nvme" {
    match name "nvme0n1p1";
    display_name "NVME";        # → HA sensors: "Disk NVME Total", "Disk NVME Free", etc.
}
```

Without `display_name`, sensor names use the block name: "Disk nvme Total", "Disk nvme Free", etc.

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
| `retain` | `on` | Retain mode: `on` (retain all) or `off` (no retention) |
| `keepalive` | `60` | Keepalive interval (seconds) |

**Retain modes:**
| Mode | Description |
|------|-------------|
| `off` | Don't retain any messages |
| `on` | Retain all messages (default) |

When the service disconnects, `{"state": "offline"}` is sent to all JSON topics (if retain is enabled).

### Home Assistant Integration

```nginx
homeassistant {
    discovery on;              # Enable MQTT Discovery
    discovery_prefix "homeassistant";  # Discovery topic prefix
}
```

**Default values:**
| Directive | Default | Description |
|-----------|---------|-------------|
| `discovery` | `on` | Enable MQTT Discovery |
| `discovery_prefix` | `"homeassistant"` | Discovery topic prefix |

### Device Templates

Define reusable device templates for grouping sensors in Home Assistant:

```nginx
device "ups_batteries" {
    name "UPS Batteries";
    manufacturer "APC";
    model "Smart-UPS";
}
```

Reference templates in sensor configurations using `device "template_name";`:

```nginx
battery "ups_battery_1" {
    device "ups_batteries";  # Use the template above
    # ... other settings
}

custom "room_temp" {
    device "room_sensors";   # Reference another template
    # ... other settings
}
```

**Reserved device values:**

| Value | Description |
|-------|-------------|
| `device system;` | Group with the system device (default for temperature, GPU, disks, battery) |
| `device auto;` | Create a dedicated device (default for services, containers, processes, custom) |
| `device none;` | No device — create "orphan" entities without device association |

### Home Assistant Sensor Overrides

Override any Home Assistant discovery fields for sensors using the `homeassistant {}` block:

```nginx
process "nginx" {
    homeassistant {
        name "Web Server";           # Override display name
        icon "mdi:web";             # Change icon
        unit_of_measurement "%";     # Override unit
        device_class "power";        # Change device class
        state_class "measurement";   # Change state class
        entity_category "diagnostic"; # Set entity category
        enabled_by_default false;    # Disable by default
        # Any other HA discovery fields can be added here
    }
    match name "nginx";
    cpu on;
    memory on;
}
```

**Available fields in `homeassistant {}` block:**

| Field | Description |
|-------|-------------|
| `name` | Display name in Home Assistant (default: auto-generated) |
| `icon` | MDI icon name (e.g., `"mdi:thermometer"`) |
| `unit_of_measurement` | Unit of measurement |
| `device_class` | HA device class (e.g., `temperature`, `power`, `energy`) |
| `state_class` | HA state class (e.g., `measurement`, `total`, `total_increasing`) |
| `entity_category` | Entity category (`diagnostic`, `config`) |
| `enabled_by_default` | Enable sensor by default (`true`/`false`, default: `true`) |
| *Any other field* | Additional fields are passed directly to HA discovery payload |

**Note:** The `homeassistant {}` block applies to all sensors created by the collector. For collectors that create multiple sensors (e.g., process, container), the overrides are applied to all of them.
| `device "name";` | Use a device template defined with `device "name" { ... }` |

### Default Settings

```nginx
defaults {
    update_interval 10s;       # Collection interval (supports: ms, s, m, h, d)
    smaps off;                 # PSS/USS memory metrics (requires root)
}
```

**Default values:**
| Directive | Default | Description |
|-----------|---------|-------------|
| `update_interval` | `10s` | Collection interval |
| `smaps` | `off` | PSS/USS memory (requires root) |

**Duration formats:** `ms` (milliseconds), `s` (seconds), `m` (minutes), `h` (hours), `d` (days)

#### Per-Source-Type Defaults

You can define default settings for each source type within the `defaults` block:

```nginx
defaults {
    update_interval 10s;
    smaps off;
    
    # All processes will have these settings by default
    process {
        cpu on;
        memory on;
        smaps on;        # Enable smaps for all processes
        disk on;         # Read/write totals (bytes)
        fds off;
        threads off;
    }
    
    # All containers will have these settings by default
    container {
        cpu on;
        memory on;
        network on;      # Enable network for all containers
        disk off;
        state on;
        health on;
    }
    
    # All services will have these settings by default
    service {
        cpu on;
        memory on;
        state on;
        restart_count on;
    }
    
    # All batteries will have these settings by default
    battery {
        capacity on;
        voltage on;
        power on;
        health on;
    }
    
    # All custom sensors will have these settings by default
    custom {
        type number;
        timeout 10s;
    }
}
```

Individual source blocks can still override these defaults:

```nginx
# Uses process defaults (smaps on from above)
process "nginx" {
    match name "nginx";
}

# Overrides process defaults (smaps off for this one)
process "low-priority" {
    match name "background-task";
    smaps off;
}
```

### Auto-Discovery

Penguin Metrics can automatically discover sensors, batteries, AC power supplies, containers, services, processes, and disks.
All auto-discovery settings are grouped inside the `auto_discovery { }` block:

```nginx
auto_discovery {

    # Auto-discover temperature sensors
    temperatures {
        auto on;
        # source thermal;  # "thermal" or "hwmon" (default: thermal)
        # update_interval 15s;   # Optional override
    }

    # Auto-discover batteries
    batteries {
        auto on;
        # current off;            # Optional per-metric override
        # temperature on;         # Enable temperature metrics
        # update_interval 30s;
    }

    # Auto-discover running Docker containers (with filter)
    containers {
        auto on;
        filter "myapp-*";
        # disk_rate on;           # Override defaults.container values
        # update_interval 10s;
    }

    # Auto-discover systemd services (filter REQUIRED for safety)
    services {
        auto on;
        filter "docker*";          # REQUIRED - too many services otherwise
        # smaps on;
    }

    # Auto-discover processes (filter REQUIRED for safety)
    processes {
        auto on;
        filter "python*";           # REQUIRED - thousands of processes otherwise
        # smaps on;
    }

    # Auto-discover external power supplies (non-battery)
    ac_powers {
        auto on;
        # filter "axp*";
        # exclude "usb*";
        # update_interval 30s;
    }

    # Auto-discover network interfaces
    networks {
        auto on;
        # filter "eth*";            # Only Ethernet
        # exclude "lo";             # Exclude loopback
        # rate on;                  # Enable bytes rate (KiB/s)
        # update_interval 10s;
    }

    # Auto-discover disk partitions
    disks {
        auto on;
        filter "*";                 # All partitions
        # exclude "loop*";
        # update_interval 60s;
    }

    # Auto-discover fans (hwmon fan*_input)
    # fans {
    #     auto on;
    #     # filter "fan*";
    #     # update_interval 10s;
    # }
}
```

**Multiple filters and excludes:**

```nginx
auto_discovery {
    temperatures {
        auto on;
        source hwmon;          # Use hwmon instead of thermal zones
        filter "nvme*";        # Include NVMe sensors
        filter "soc*";         # Include SoC sensors
        exclude "test*";       # Exclude test sensors
    }
}
```

**Logic:**
- If **any exclude** pattern matches → excluded
- If filters defined and **any matches** → included
- If no filters → include all (except excluded)
- Auto blocks **inherit per-source defaults**, then apply any boolean flags and `update_interval`
  specified directly inside the auto block (e.g., `batteries { current off; temperature on; }`).

### Dynamic Auto-Refresh

By default, auto-discovery runs only at startup. Enable `auto_refresh_interval` (top-level setting) to periodically check for new or removed sources:

```nginx
# Check for new/removed sources every 60 seconds (0 = disabled)
auto_refresh_interval 60s;
```

When enabled:
- **New auto-discovered sources** (services, containers, processes, temperatures, batteries, disks, networks, fans) matching filters are automatically added
- **Removed** auto-discovered sources are cleaned up from HA and JSON state
- Home Assistant sensors are registered/unregistered dynamically
- Manual configurations are never affected
- Logs at `INFO` level only when sources are added/removed (not on every check)

**Manual definitions override auto-discovered:**

```nginx
# This overrides the auto-discovered "soc-thermal"
temperature "soc-thermal" {
    match zone "soc-thermal";
    update_interval 5s;
}
```

**Stale sensor cleanup:**

When a sensor disappears (e.g., NVMe removed), it will be automatically removed
from Home Assistant on the next Penguin Metrics restart. State is stored in:
- Primary: `/var/lib/penguin-metrics/registered_sensors.json`
- Fallback: `~/.penguin-metrics/registered_sensors.json`

Custom location:
```nginx
homeassistant {
    state_file "/custom/path/sensors.json";
}
```

### Logging Configuration

```nginx
logging {
    level info;                # Console log level
    colors on;                 # Colored console output (auto-detect TTY)
    
    # File logging
    file "/var/log/penguin-metrics/penguin-metrics.log";
    file_level debug;          # File log level
    file_max_size 10;          # Max size in MB before rotation
    file_keep 5;               # Number of rotated files to keep
    
    # Custom format (advanced)
    # format "%(asctime)s [%(levelname)s] %(name)s: %(message)s";
}
```

**Default values:**
| Directive | Default | Description |
|-----------|---------|-------------|
| `level` | `"info"` | Console log level |
| `colors` | `on` | Colored output (if TTY) |
| `file` | *(none)* | Log file path |
| `file_level` | `"debug"` | File log level |
| `file_max_size` | `10` | Max file size (MB) |
| `file_keep` | `5` | Backup files to keep |

**Log levels:** `debug`, `info`, `warning`, `error`

**Command-line overrides:**
```bash
# Verbose (INFO level)
python -m penguin_metrics -v config.conf

# Debug (DEBUG level)  
python -m penguin_metrics -d config.conf

# Quiet (ERROR only)
python -m penguin_metrics -q config.conf

# Custom log file
python -m penguin_metrics --log-file /tmp/pm.log config.conf

# Disable colors
python -m penguin_metrics --no-color config.conf
```

### System Metrics

```nginx
system "My Server" {
    # The system name becomes the device name in Home Assistant
    # Optional: device "template_name"; to use a device template
    
    cpu on;                    # Total CPU usage
    cpu_per_core off;          # Per-core CPU usage
    memory on;                 # Memory usage
    swap on;                   # Swap usage
    load on;                   # Load average (1, 5, 15 min)
    uptime on;                 # System uptime
    gpu off;                   # GPU metrics (if available)
    
    update_interval 5s;
}
```

**Note:** Temperature sensors are configured separately via `auto_discovery { temperatures { ... } }` (see Auto-Discovery section).

**Default values:**
| Directive | Default | Description |
|-----------|---------|-------------|
| `cpu` | `on` | Total CPU usage |
| `cpu_per_core` | `off` | Per-core CPU usage |
| `memory` | `on` | Memory usage |
| `swap` | `on` | Swap usage |
| `load` | `on` | Load average |
| `uptime` | `on` | System uptime |
| `gpu` | `off` | GPU metrics |
| `disk_io` | `on` | Disk read/write totals (bytes) |
| `disk_io_rate` | `off` | Disk read/write rate (KiB/s) |
| `cpu_freq` | `on` | CPU frequency current/min/max (MHz; N/A on some ARM/virtual) |
| `process_count` | `on` | Total and running process count |
| `boot_time` | `on` | Boot time (timestamp for HA) |
| `update_interval` | *(from defaults)* | Override default interval |

### Process Monitoring

```nginx
# Match by exact process name
process "docker" {
    match name "dockerd";
    
    cpu on;
    memory on;
    smaps on;                  # PSS/USS + Real PSS/USS (requires root)
    disk on;                   # Read/write totals (bytes)
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
| `cpu` | `on` | CPU usage (normalized to 0-100%) |
| `memory` | `on` | Memory (RSS) |
| `smaps` | *(from defaults)* | PSS/USS + Real PSS/USS memory |
| `disk` | `off` | Read/write totals (bytes) |
| `disk_rate` | `off` | Read/write rate (KiB/s) |
| `fds` | `off` | Open file descriptors (enable for open files monitoring) |
| `threads` | `off` | Thread count (enable for thread monitoring) |
| `aggregate` | `off` | Sum metrics from all matches |
| `update_interval` | *(from defaults)* | Override default interval |

**Memory metrics when `smaps on`:**
- `memory_rss_mb`: Standard RSS (Resident Set Size)
- `memory_pss_mb`: Proportional Set Size (includes file-backed)
- `memory_uss_mb`: Unique Set Size (includes file-backed)
- `memory_real_pss_mb`: Real PSS (excludes file-backed mappings)
- `memory_real_uss_mb`: Real USS (excludes file-backed mappings)

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
    memory on;                 # Memory Cgroup (includes cache, use smaps for accurate)
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
| `cpu` | `on` | CPU usage (normalized to 0-100%) |
| `memory` | `on` | Memory Cgroup (includes cache) |
| `smaps` | *(from defaults)* | PSS/USS + Real PSS/USS aggregated |
| `state` | `on` | Service state (only 'active' collects metrics) |
| `restart_count` | `off` | Number of restarts |
| `update_interval` | *(from defaults)* | Override default interval |

**Note:** Metrics are only collected when service state is `active`. States like `activating` or `reloading` don't collect cgroup metrics.

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
| `cpu` | `on` | CPU usage % (normalized to 0-100%) |
| `memory` | `on` | Memory usage |
| `network` | `off` | Network RX/TX bytes |
| `disk` | `off` | Block I/O |
| `state` | `on` | Container state |
| `health` | `off` | Healthcheck status |
| `uptime` | `off` | Container uptime |
| `update_interval` | *(from defaults)* | Override default interval |

**Match types:**
| Type | Example | Description |
|------|---------|-------------|
| `name` | `match name "nginx";` | Exact container name |
| `pattern` | `match pattern "web-.*";` | Regex on name |
| `image` | `match image "postgres:";` | Image name (substring) |
| `label` | `match label "app=web";` | Container label |

### Battery Monitoring

**Metrics (published as JSON fields):**
- `state` - charging/discharging/full/not charging/not_found
- `capacity` - charge level (%)
- `voltage` - current voltage (V)
- `current` - current (A, sign preserved)
- `power` - power (W, sign preserved)
- `health` - battery health
- `cycles` - charge cycle count
- `temperature` - battery temperature (°C)
- `time_to_empty` - minutes remaining
- `time_to_full` - minutes to full charge
- `energy_now`, `energy_full`, `energy_full_design` - energy (Wh)
- `present` - presence flag (0/1)
- `technology` - chemistry (e.g., Li-ion)
- `voltage_max`, `voltage_min` - current voltage limits (V)
- `voltage_max_design`, `voltage_min_design` - design voltage limits (V)
- `constant_charge_current`, `constant_charge_current_max` - charge currents (A)
- `charge_full_design` - design full charge (mAh)

```nginx
battery "main" {
    # Match criteria (exactly one):
    match name "BAT0";             # Battery name
    # match path "/sys/class/power_supply/BAT0";  # Or by sysfs path
    
    capacity on;               # Charge percentage
    voltage on;                # Current voltage
    current on;                # Current amperage (sign preserved: +charge / -discharge)
    power on;                  # Power (sign preserved)
    health on;                 # Battery health
    energy_now on;             # Current energy (Wh)
    energy_full on;            # Full energy (Wh)
    energy_full_design on;     # Design full energy (Wh)
    cycles on;                 # Charge cycles
    temperature on;            # Battery temperature
    time_to_empty on;          # Estimated time remaining
    time_to_full on;           # Time to full charge
    present on;                # Presence flag (0/1)
    technology on;             # Chemistry (e.g., Li-ion)
    voltage_max on;            # Current max voltage (V)
    voltage_min on;            # Current min voltage (V)
    voltage_max_design on;     # Design max voltage (V)
    voltage_min_design on;     # Design min voltage (V)
    constant_charge_current on;     # Target charge current (A)
    constant_charge_current_max on; # Max charge current (A)
    charge_full_design on;     # Design full charge (mAh)
    
    update_interval 30s;
}
```

**Default values:**
| Directive | Default | Description |
|-----------|---------|-------------|
| `match name` | *(required)* | Battery name (BAT0, etc.) |
| `match path` | *(alternative)* | Full path to battery in sysfs |
| `capacity` | `on` | Charge percentage |
| `voltage` | `on` | Current voltage |
| `current` | `on` | Current amperage (sign preserved) |
| `power` | `on` | Power (sign preserved) |
| `health` | `on` | Battery health |
| `energy_now` | `on` | Current energy (Wh) |
| `energy_full` | `on` | Full energy (Wh) |
| `energy_full_design` | `on` | Design full energy (Wh) |
| `cycles` | `off` | Charge cycle count |
| `temperature` | `off` | Battery temperature |
| `time_to_empty` | `off` | Time remaining |
| `time_to_full` | `off` | Time to full charge |
| `present` | `off` | Presence flag |
| `technology` | `off` | Battery chemistry |
| `voltage_max` | `off` | Current max voltage |
| `voltage_min` | `off` | Current min voltage |
| `voltage_max_design` | `off` | Design max voltage |
| `voltage_min_design` | `off` | Design min voltage |
| `constant_charge_current` | `off` | Target charge current |
| `constant_charge_current_max` | `off` | Max charge current |
| `charge_full_design` | `off` | Design full charge (mAh) |
| `update_interval` | *(from defaults)* | Override default interval |

Status (`state`) is always collected and published (required for availability/HA) and is not configurable.

### AC Power Monitoring

Monitors external power supply (mains) presence from `/sys/class/power_supply/<device>/online`.

**Metrics (published as JSON fields):**
- `state` - online/not_found (source availability: "online" if data read successfully, "not_found" if source unavailable)
- `online` - boolean: `true` if external power is present, `false` otherwise

```nginx
ac_power "main" {
    # Match criteria (exactly one):
    match name "axp22x-ac";       # Sysfs device name
    # match path "/sys/class/power_supply/axp22x-ac";  # Or by full path
    
    device system;                # Group with system device (default)
    # update_interval 30s;
    # homeassistant { name "AC Power"; icon "mdi:power-plug"; }
}
```

**Default values:**
| Directive | Default | Description |
|-----------|---------|-------------|
| `match name` | *(required)* | Sysfs device name (e.g. axp22x-ac) |
| `match path` | *(alternative)* | Full path to power_supply directory |
| `device` | `system` | Group with system device (via parent device) |
| `update_interval` | *(from defaults)* | Override default interval |

**Note:** AC power sensors publish JSON with `online` (boolean) and `state` fields. Exposed to Home Assistant as a `binary_sensor` with `ON`/`OFF` derived from `online`.

### Network Interfaces

Monitors network interfaces via `psutil.net_io_counters(pernic=True)` and `psutil.net_if_stats()`.

**Metrics (published as JSON fields):**
- `bytes_sent`, `bytes_recv` - Total bytes
- `packets_sent`, `packets_recv` - Packet counts
- `errin`, `errout` - Error counts
- `dropin`, `dropout` - Dropped packet counts
- `bytes_sent_rate`, `bytes_recv_rate` - Rate (KiB/s) when `rate on`
- `packets_sent_rate`, `packets_recv_rate` - Packet rate (p/s) when `packets_rate on`
- `isup` - Interface up/down (boolean, binary_sensor in HA)
- `speed` - Link speed (Mbps)
- `mtu` - MTU
- `duplex` - full/half
- `state` - online/not_found (source availability)

```nginx
network "eth0" {
    match name "eth0";           # Interface name (required)
    device system;               # Group with system device (default)
    bytes on;                    # bytes_sent, bytes_recv (bytes)
    packets off;                 # packets_sent, packets_recv
    errors off;                  # errin, errout
    drops off;                   # dropin, dropout
    rate off;                    # bytes_sent_rate, bytes_recv_rate (KiB/s)
    packets_rate off;            # packets_sent_rate, packets_recv_rate (p/s)
    isup on;                     # Interface up/down (binary_sensor)
    speed off;                   # Speed (Mbps)
    mtu off;
    duplex off;
    rssi off;                    # Wi-Fi signal (dBm) for wireless interfaces
    # update_interval 10s;
}
```

**Default values (defaults.network):** `bytes` on, `packets`/`errors`/`drops`/`rate`/`packets_rate` off, `isup` on, `speed`/`mtu`/`duplex` off, `rssi` off.

Optional `rssi on`: Wi-Fi signal strength (dBm) for wireless interfaces (uses `iw` or `iwconfig`).

### Fan (RPM)

Fan speed from hwmon sysfs (`/sys/class/hwmon/hwmon*/fan*_input`). Manual config or auto-discovery via `auto_discovery { fans { auto on; } }`.

```nginx
fan "cpu_fan" {
    match hwmon "hwmon0";      # Hwmon directory name (required)
    device system;
}
```

Metrics: `fan1_rpm`, `fan2_rpm`, or `rpm` (single fan). Unit: RPM.

### Custom Sensors

The block name (e.g., `"room_temp"`) is the sensor ID, used for MQTT topics.
Use the `homeassistant {}` block to override any Home Assistant discovery fields.

```nginx
# Read from command output
# MQTT topic: {prefix}/custom/room_temp
custom "room_temp" {
    command "cat /sys/bus/w1/devices/28-*/temperature";
    
    type number;               # number, string, json
    scale 0.001;               # Multiply result
    
    # Home Assistant sensor overrides
    homeassistant {
        name "Room Temperature";  # Display name in HA (default: use ID)
        icon "mdi:thermometer";
        unit_of_measurement "°C";
        device_class temperature;
        state_class measurement;
        # Any other HA discovery fields can be added here
    }
    
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
    homeassistant {
        name "WAN IP Address";
    }
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
| `scale` | `1.0` | Multiply numeric result by this |
| `timeout` | `5s` | Command timeout |
| `update_interval` | *(from defaults)* | Override default interval |

**Home Assistant overrides** (in `homeassistant {}` block):
| Field | Description |
|-------|-------------|
| `name` | Display name in Home Assistant (default: use sensor ID) |
| `icon` | MDI icon name (e.g., `"mdi:thermometer"`) |
| `unit_of_measurement` | Unit of measurement |
| `device_class` | HA device class (e.g., `temperature`, `power`) |
| `state_class` | HA state class (e.g., `measurement`, `total`) |
| `entity_category` | Entity category (e.g., `diagnostic`, `config`) |
| `enabled_by_default` | Enable sensor by default (default: `true`) |
| *Any other field* | Additional fields are passed directly to HA discovery |

**Output types:**
| Type | Description |
|------|-------------|
| `number` | Parse as float, apply `scale` |
| `string` | Use raw output as-is |
| `json` | Parse as JSON object |

**JSON payload:**
Custom sensors publish JSON with:
- `value`: The parsed command output
- `state`: `"online"` (command succeeded) or `"not_found"` (command failed)

### Custom Binary Sensors

Custom binary sensors interpret command execution results as ON/OFF states. Perfect for connectivity checks, service status, or any boolean condition.

The block name (e.g., `"server_ping"`) is the sensor ID, used for MQTT topics.
Use the `homeassistant {}` block to override any Home Assistant discovery fields.

```nginx
# Ping check (returns ON if host is reachable, OFF if not)
# MQTT topic: {prefix}/custom_binary/server_ping
custom_binary "server_ping" {
    command "ping -c 1 -W 1 8.8.8.8 > /dev/null 2>&1";
    
    value_source returncode;         # Default: "returncode" (0=ON, non-zero=OFF)
    # value_source output;          # Alternative: parse command output
    
    # invert on;                    # Invert ON ↔ OFF
    
    # Home Assistant sensor overrides
    homeassistant {
        name "Server Reachability";
        icon "mdi:network";
        device_class connectivity;   # Optional: connectivity, motion, etc.
    }
    
    update_interval 30s;
    timeout 5s;
}

# Check service status using output parsing
custom_binary "nginx_running" {
    command "systemctl is-active nginx";
    value_source output;            # Parse output: "active" = ON, other = OFF
    update_interval 10s;
}
```

**Default values:**
| Directive | Default | Description |
|-----------|---------|-------------|
| `command` | *(required)* | Shell command to execute |
| `script` | *(none)* | Script path (alternative to command) |
| `value_source` | `"returncode"` | How to interpret result: `returncode` or `output` |
| `invert` | `off` | Invert the value (ON ↔ OFF) |
| `timeout` | `5s` | Command timeout |
| `update_interval` | *(from defaults)* | Override default interval |

**Value sources:**
| Source | Description |
|-------|-------------|
| `returncode` | `0` = ON, non-zero = OFF |
| `output` | Parse stdout: `on`/`true`/`1`/`yes`/`ok`/`online`/`up` = ON, `off`/`false`/`0`/`no`/`error`/`offline`/`down` = OFF, empty = OFF |

**Home Assistant overrides** (in `homeassistant {}` block):
Same as custom sensors (see above). Custom binary sensors are automatically registered as `binary_sensor` entities in Home Assistant.

**JSON payload:**
Custom binary sensors publish JSON with:
- `state`: `"ON"` or `"OFF"` (the binary value)
- `state`: `"online"` (always online, even if command failed - failed = OFF)

### Temperature Zones (Standalone)

Manually configure specific temperature sensors (overrides auto-discovered with same name):

```nginx
temperature "cpu" {
    # Match criteria (exactly one):
    match zone "cpu-thermal";  # Thermal zone name
    # match path "/sys/class/thermal/thermal_zone0/temp";  # Or by sysfs path
    # match hwmon "soc_thermal_sensor0";  # Or by hwmon sensor name
    
    update_interval 5s;
}
```

**Note:** Temperature sensors publish JSON with `temp` and `state` fields:
- `state`: `"online"` (sensor found) or `"not_found"` (sensor missing)
- `temp`: Temperature value in Celsius
- Optional: `high` and `critical` thresholds if available

### Include Files

```nginx
# Include single file
include "/etc/penguin-metrics/processes.conf";

# Include with glob pattern
include "/etc/penguin-metrics/conf.d/*.conf";
```

## MQTT Topics

### JSON Payload Topics

Each source publishes all its metrics as a single JSON payload to one topic:

```
{topic_prefix}/{source_type}/{source_name}
```

**Examples:**
```
penguin_metrics/system
  → {"cpu_percent": 45.2, "memory_percent": 67.8, "load_1": 1.2, ...}

penguin_metrics/process/docker
  → {"cpu_percent": 2.5, "memory_rss_mb": 512.3, "state": "running", ...}

penguin_metrics/service/docker-service
  → {"cpu_percent": 1.8, "memory_mb": 1024.5, "state": "active", ...}

penguin_metrics/docker/homeassistant
  → {"cpu_percent": 5.2, "memory_mb": 2048.0, "state": "running", ...}

penguin_metrics/temperature/cpu-thermal
  → {"temp": 42.5, "state": "online", "high": 70.0, "critical": 85.0}

penguin_metrics/battery/main
  → {"capacity": 85, "state": "charging", "voltage": 12.6, ...}
```

### Availability Topics

**Global application status:**
```
{topic_prefix}/status  → "online" / "offline"
```

**Local source state** (included in JSON payload):
- Each source includes a `state` field in its JSON payload
- Values: `"online"`, `"offline"`, `"running"`, `"active"`, `"not_found"`, etc.
- Home Assistant uses `value_template` to extract both the metric value and availability state

### Home Assistant Discovery

Discovery messages are published to:
```
{discovery_prefix}/sensor/{unique_id}/config
```

Each sensor uses `value_template` to extract its metric from the source's JSON payload:
```json
{
  "state_topic": "penguin_metrics/process/docker",
  "value_template": "{{ value_json.cpu_percent }}",
  "availability": [
    {
      "topic": "penguin_metrics/status",
      "payload_available": "online",
      "payload_not_available": "offline"
    },
    {
      "topic": "penguin_metrics/process/docker",
      "value_template": "{{ 'online' if value_json.state == 'running' else 'offline' }}",
      "payload_available": "online",
      "payload_not_available": "offline"
    }
  ]
}
```

## Permissions

### For smaps (PSS/USS memory)

#### What is PSS and USS?

| Metric | Formula | Description |
|--------|---------|-------------|
| **RSS** | Private + Shared | Total memory in RAM (overestimates if shared) |
| **PSS** | Private + Shared/N | Proportional Set Size — fair share of shared memory |
| **USS** | Private only | Unique Set Size — memory freed when process exits |
| **Real PSS** | Pss_Anon + Pss_Shm + SwapPss | PSS excluding file-backed mappings |
| **Real USS** | Anonymous | USS excluding file-backed mappings (mmap'd files) |

**Why use PSS/USS?**
- RSS counts shared memory (libc, etc.) fully for each process
- 10 processes sharing 50MB libc → RSS shows 500MB total ❌
- PSS divides shared memory: each process shows 5MB → 50MB total ✓
- USS shows only private memory — what's freed on `kill`

**Why use Real PSS/USS?**
- Standard PSS/USS includes file-backed mappings (mmap'd files)
- File-backed mappings can be evicted from RAM by the kernel
- Applications like qBittorrent map large files but don't actually use that much RAM
- Real PSS/USS excludes file-backed mappings → accurate RAM usage
- **Real PSS** = `Pss_Anon + Pss_Shm + SwapPss` (from `/proc/PID/smaps`)
- **Real USS** = `Anonymous` (from `/proc/PID/smaps`)

**Example:**
- qBittorrent maps 3GB of torrent files → RSS shows 3GB
- Real USS shows 200MB → actual RAM usage ✓

#### Granting permissions

Reading `/proc/PID/smaps` of other processes requires elevated privileges.

**Option 1: Run as root** (simplest)
```bash
sudo penguin-metrics config.conf
```

**Option 2: CAP_SYS_PTRACE capability** (recommended for systemd)
```bash
# For installed package
sudo setcap cap_sys_ptrace+ep $(which python3)

# For virtualenv
sudo setcap cap_sys_ptrace+ep /opt/penguin-metrics/.venv/bin/python3

# Verify
getcap /opt/penguin-metrics/.venv/bin/python3
# Output: /opt/penguin-metrics/.venv/bin/python3 cap_sys_ptrace=ep
```

**Option 3: In systemd service file**
```ini
[Service]
# Run as root
User=root

# Or use AmbientCapabilities (requires User=non-root)
User=penguin-metrics
AmbientCapabilities=CAP_SYS_PTRACE
```

**Option 4: In Docker** (docker-compose.yml)
```yaml
services:
  penguin-metrics:
    cap_add:
      - SYS_PTRACE
    pid: host  # Required to see host processes
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

Solutions:
- Run as root: `sudo penguin-metrics config.conf`
- Grant capability: `sudo setcap cap_sys_ptrace+ep $(which python3)`
- Disable smaps: `smaps off;` in config (will use RSS instead)

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
# Subscribe to all topics (JSON payloads)
mosquitto_sub -h 10.13.1.100 -p 1833 \
  -u penguin_metrics -P password \
  -t "penguin_metrics/#" -v

# In another terminal, run the service
python -m penguin_metrics -v config.conf

# Example output:
# penguin_metrics/system {"cpu_percent": 45.2, "memory_percent": 67.8, ...}
# penguin_metrics/process/docker {"cpu_percent": 2.5, "state": "running", ...}
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
    # Result contains a dict with all metrics
    print(result.data)  # {"cpu_percent": 45.2, "memory_percent": 67.8, ...}
    print(f"Available: {result.available}")

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

GPLv3 License

## Support the Developer and the Project

* [GitHub Sponsors](https://github.com/sponsors/ClusterM)

* [Buy Me A Coffee](https://www.buymeacoffee.com/cluster)

* [Sber](https://messenger.online.sberbank.ru/sl/Lnb2OLE4JsyiEhQgC)

* [Donation Alerts](https://www.donationalerts.com/r/clustermeerkat)

* [Boosty](https://boosty.to/cluster)

