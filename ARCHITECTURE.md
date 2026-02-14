# Penguin Metrics - Architecture

Detailed documentation of the project structure, modules, and their responsibilities.

## Project Structure

```
penguin_metrics/
├── __init__.py              # Package metadata (version, author)
├── __main__.py              # CLI entry point
├── app.py                   # Main application orchestrator
├── const.py                 # Application constants (name, version, URL)
├── logging.py               # Logging configuration
│
├── config/                  # Configuration parsing
│   ├── __init__.py
│   ├── lexer.py             # Tokenizer for nginx-like syntax
│   ├── parser.py            # Recursive descent parser
│   ├── schema.py            # Configuration dataclasses
│   └── loader.py            # File loading and validation
│
├── collectors/              # Metric collectors
│   ├── __init__.py
│   ├── base.py              # Abstract collector interface
│   ├── system.py            # System metrics (CPU, RAM, etc.)
│   ├── temperature.py       # Thermal zones
│   ├── disk.py              # Disk space monitoring
│   ├── process.py           # Process monitoring
│   ├── service.py           # Systemd services
│   ├── container.py         # Docker containers
│   ├── battery.py           # Battery status
│   ├── ac_power.py          # External power (AC/mains) status
│   ├── network.py           # Network interface metrics (bytes, packets, rate, rssi, isup, speed, mtu, duplex)
│   ├── fan.py               # Fan RPM from hwmon fan*_input
│   ├── custom.py            # Custom commands/scripts
│   └── gpu.py               # GPU metrics
│
├── mqtt/                    # MQTT communication
│   ├── __init__.py
│   ├── client.py            # Async MQTT client
│   └── homeassistant.py     # HA Discovery integration
│
├── models/                  # Data models
│   ├── __init__.py
│   ├── device.py            # HA Device model
│   └── sensor.py            # HA Sensor model
│
└── utils/                   # Utility functions
    ├── __init__.py
    ├── smaps.py             # /proc/PID/smaps parser
    ├── cgroup.py            # cgroup v1/v2 reader
    └── docker_api.py        # Docker socket API client
```

---

## Core Modules

### `__main__.py` - CLI Entry Point

Command-line interface for the application.

**Functions:**
- `main()` - Parse arguments and run application

**CLI Arguments:**
```
penguin-metrics [config] [-v|--verbose] [-d|--debug] [-q|--quiet] 
                 [--log-file PATH] [--no-color] [--validate] [--version]
```

### `const.py` - Application Constants

Application metadata and default values.

**Constants:**
- `APP_NAME = "Penguin Metrics"`
- `APP_VERSION = "0.0.1"`
- `APP_URL = "https://github.com/clusterm/penguin-metrics"`
- `DEFAULT_MQTT_PORT = 1883`
- `DEFAULT_MQTT_KEEPALIVE = 60`
- `DEFAULT_UPDATE_INTERVAL = 10.0`
- `DEFAULT_QOS = 0`

### `logging.py` - Logging Configuration

Custom logging setup with colored output and file rotation.

**Functions:**
- `setup_logging(config: LogConfig | LoggingConfig)` - Configure logging

**Classes:**
- `LogConfig` - CLI logging configuration
- `ColoredFormatter` - Console formatter with colors
- `PlainFormatter` - Plain console formatter
- `RotatingFileHandler` - File handler with rotation

---

### `app.py` - Application Orchestrator

Main application class that coordinates all components.

**Classes:**

#### `Application`
Main application that manages collectors, MQTT client, and HA discovery.

```python
class Application:
    def __init__(self, config: Config)
    
    # Public methods
    async def start() -> None          # Start the application
    async def stop() -> None           # Stop gracefully
    async def run() -> None            # Run until shutdown
    
    # Internal methods
    def _create_collectors() -> list[Collector]
    async def _initialize_collectors() -> None
    async def _run_collector(collector: Collector) -> None
    async def _auto_refresh_loop(interval: float) -> None
    async def _refresh_auto_discovered() -> None
    async def _add_collector(collector: Collector) -> None
    async def _remove_collector(collector_id: str) -> None
    def _setup_signal_handlers() -> None
    def _signal_handler() -> None
    # Auto-discovery methods
    def _auto_discover_temperatures(exclude, topic_prefix) -> list[Collector]
    def _auto_discover_batteries(exclude, topic_prefix) -> list[Collector]
    def _auto_discover_ac_power(exclude, topic_prefix) -> list[Collector]
    async def _auto_discover_containers(exclude, topic_prefix) -> list[Collector]
    def _auto_discover_services(exclude, topic_prefix) -> list[Collector]
    def _auto_discover_processes(exclude, topic_prefix) -> list[Collector]
    def _auto_discover_disks(exclude, topic_prefix) -> list[Collector]
    def _auto_discover_networks(exclude, topic_prefix) -> list[Collector]
```

**Functions:**
- `run_app(config_path)` - Load config and run application

---

## Configuration Module (`config/`)

### `lexer.py` - Tokenizer

Converts configuration text into tokens.

**Classes:**

#### `TokenType` (Enum)
Token types: `IDENTIFIER`, `STRING`, `NUMBER`, `DURATION`, `BOOLEAN`, `LBRACE`, `RBRACE`, `SEMICOLON`, `INCLUDE`, `EOF`, `ERROR`

#### `Token`
```python
@dataclass
class Token:
    type: TokenType
    value: str | int | float | bool
    line: int
    column: int
    raw: str = ""
```

#### `Lexer`
```python
class Lexer:
    def __init__(self, source: str, filename: str = "<string>")
    
    def next_token() -> Token           # Get next token
    def tokenize() -> Iterator[Token]   # Generate all tokens
    
    # Internal methods
    def _current() -> str               # Current character
    def _peek(offset: int) -> str       # Look ahead
    def _advance() -> str               # Move forward
    def _skip_whitespace() -> None
    def _skip_comment() -> bool
    def _read_string() -> Token
    def _read_number_or_duration() -> Token
    def _read_identifier() -> Token
```

**Supported syntax:**
- Identifiers: `mqtt`, `host`, `cpu_per_core`
- Strings: `"quoted string"`, `'single quotes'`
- Numbers: `123`, `45.67`
- Durations: `10s`, `5m`, `1h`, `30ms`, `1d`
- Booleans: `on`, `off`, `true`, `false`
- Comments: `# single line`, `/* multi line */`

---

### `parser.py` - Recursive Descent Parser

Parses tokens into configuration tree.

**Classes:**

#### `Directive`
```python
@dataclass
class Directive:
    name: str
    values: list[Any]
    line: int
    column: int
    
    @property
    def value(self) -> Any              # First value or None
    def get(index: int, default) -> Any
```

#### `Block`
```python
@dataclass
class Block:
    type: str
    name: str | None
    directives: list[Directive]
    blocks: list[Block]
    line: int
    column: int
    
    def get_directive(name: str) -> Directive | None
    def get_directives(name: str) -> list[Directive]
    def get_value(name: str, default) -> Any
    def get_all_values(name: str) -> list[Any]  # Get all values for directive (for multiple filters/excludes)
    def get_block(type_name: str) -> Block | None
    def get_blocks(type_name: str) -> list[Block]
```

#### `ConfigDocument`
```python
@dataclass
class ConfigDocument:
    blocks: list[Block]
    directives: list[Directive]
    filename: str
    
    def get_block(type_name: str) -> Block | None
    def get_blocks(type_name: str) -> list[Block]
    def get_directive(name: str) -> Directive | None
    def get_value(name: str, default: Any = None) -> Any
    def merge(other: ConfigDocument) -> None
```

#### `ConfigParser`
```python
class ConfigParser:
    def __init__(self, source, filename, base_path, included_files)
    
    def parse() -> ConfigDocument
    
    # Internal methods
    def _parse_include() -> ConfigDocument
    def _parse_block_or_directive() -> Block | Directive
    def _parse_block_body(...) -> Block
```

**Grammar:**
```
document    := (block | directive | include)*
block       := IDENTIFIER [STRING] '{' (block | directive)* '}'
directive   := IDENTIFIER value* ';'
value       := STRING | NUMBER | DURATION | BOOLEAN | IDENTIFIER
include     := 'include' STRING ';'
```

---

### `schema.py` - Configuration Dataclasses

Typed configuration structures with validation.

**Enums:**
- `RetainMode`: `ON`, `OFF` - MQTT message retention
- `ProcessMatchType`: `NAME`, `PATTERN`, `PID`, `PIDFILE`, `CMDLINE`
- `ServiceMatchType`: `UNIT`, `PATTERN`
- `ContainerMatchType`: `NAME`, `PATTERN`, `IMAGE`, `LABEL`

**Configuration Classes:**

```python
@dataclass
class MQTTConfig:
    host: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    client_id: str | None = None
    topic_prefix: str = "penguin_metrics"
    qos: int = 1
    retain: RetainMode = RetainMode.ON  # on/off (default: on)
    keepalive: int = 60
    
    def should_retain() -> bool  # Check if messages should be retained

@dataclass
class HomeAssistantConfig:
    discovery: bool = True
    discovery_prefix: str = "homeassistant"
    state_file: str = "/var/lib/penguin-metrics/registered_sensors.json"

@dataclass
class DefaultsConfig:
    update_interval: float = 10.0
    smaps: bool = False
    # Per-source-type defaults
    process: ProcessDefaultsConfig
    service: ServiceDefaultsConfig
    container: ContainerDefaultsConfig
    battery: BatteryDefaultsConfig
    custom: CustomDefaultsConfig
    disk: DiskDefaultsConfig
    network: NetworkDefaultsConfig

@dataclass
class Config:
    mqtt: MQTTConfig
    homeassistant: HomeAssistantConfig
    defaults: DefaultsConfig
    logging: LoggingConfig
    auto_refresh_interval: float = 0  # Top-level: 0 = disabled
    device_templates: dict[str, DeviceConfig]  # Device templates for grouping
    # Auto-discovery configs (parsed from auto_discovery { ... } block)
    auto_temperatures: AutoDiscoveryConfig
    auto_batteries: AutoDiscoveryConfig
    auto_containers: AutoDiscoveryConfig
    auto_services: AutoDiscoveryConfig
    auto_processes: AutoDiscoveryConfig
    auto_disks: AutoDiscoveryConfig
    auto_ac_powers: AutoDiscoveryConfig
    auto_networks: AutoDiscoveryConfig
    auto_fans: AutoDiscoveryConfig

@dataclass
class SystemConfig:
    name: str = "system"  # Optional, defaults to "system"
    device_ref: str | None = None  # "system"/"auto"/"none"/template name
    cpu: bool = True
    cpu_per_core: bool = False
    memory: bool = True
    swap: bool = True
    load: bool = True
    uptime: bool = True
    gpu: bool = False
    disk_io: bool = True
    disk_io_rate: bool = False
    cpu_freq: bool = True
    process_count: bool = True
    boot_time: bool = True
    update_interval: float | None = None

@dataclass
class ProcessConfig:
    name: str
    match: ProcessMatchConfig | None = None
    device_ref: str | None = None  # "system"/"auto"/"none"/template name
    sensor_prefix: str | None = None
    cpu: bool = True
    memory: bool = True
    smaps: bool | None = None
    disk: bool = False
    disk_rate: bool = False
    fds: bool = False
    threads: bool = False
    aggregate: bool = False
    update_interval: float | None = None
    
    def should_use_smaps(defaults: DefaultsConfig) -> bool

@dataclass
class ServiceConfig:
    name: str
    match: ServiceMatchConfig | None = None
    device_ref: str | None = None
    ha_config: HomeAssistantSensorConfig | None = None
    cpu: bool = True
    memory: bool = True
    smaps: bool | None = None
    state: bool = True
    restart_count: bool = False
    disk: bool = False
    disk_rate: bool = False
    ...

@dataclass
class ContainerConfig:
    name: str
    match: ContainerMatchConfig | None = None
    device_ref: str | None = None
    ha_config: HomeAssistantSensorConfig | None = None
    cpu: bool = True
    memory: bool = True
    network: bool = False
    network_rate: bool = False
    disk: bool = False
    disk_rate: bool = False
    state: bool = True
    health: bool = False
    uptime: bool = False
    ...

@dataclass
class BatteryConfig:
    name: str
    match: BatteryMatchConfig | None = None  # match name/path
    device_ref: str | None = None
    ha_config: HomeAssistantSensorConfig | None = None
    capacity: bool = True
    voltage: bool = True
    current: bool = True
    power: bool = True
    health: bool = True
    energy_now: bool = True
    energy_full: bool = True
    energy_full_design: bool = True
    cycles: bool = False
    temperature: bool = False
    time_to_empty: bool = False
    time_to_full: bool = False
    present: bool = False
    technology: bool = False
    voltage_max: bool = False
    voltage_min: bool = False
    voltage_max_design: bool = False
    voltage_min_design: bool = False
    constant_charge_current: bool = False
    constant_charge_current_max: bool = False
    charge_full_design: bool = False
    update_interval: float | None = None

@dataclass
class ACPowerConfig:
    name: str
    match: ACPowerMatchConfig | None = None  # match name/path
    device_ref: str | None = None  # "system"/"auto"/"none"/template name
    ha_config: HomeAssistantSensorConfig | None = None
    update_interval: float | None = None

@dataclass
class DiskConfig:
    name: str
    match: DiskMatchConfig | None = None  # match name/mountpoint/uuid
    total: bool = True
    used: bool = True
    free: bool = True
    percent: bool = True
    update_interval: float | None = None

@dataclass
class CustomSensorConfig:
    name: str  # Sensor ID, used for MQTT topics
    command: str | None = None
    script: str | None = None
    type: str = "number"  # number, string, json
    unit: str | None = None
    scale: float = 1.0
    device_class: str | None = None
    state_class: str | None = None
    timeout: float = 5.0
    ha_config: HomeAssistantSensorConfig | None = None
    ...

@dataclass
class CustomBinarySensorConfig:
    name: str  # Sensor ID, used for MQTT topics
    command: str | None = None
    script: str | None = None
    value_source: str = "returncode"  # "returncode" or "output"
    invert: bool = False  # Invert the value (ON ↔ OFF)
    timeout: float = 5.0
    ha_config: HomeAssistantSensorConfig | None = None
    ...

@dataclass
class LoggingConfig:
    level: str = "info"
    file: str | None = None
    file_level: str = "debug"
    file_max_size: int = 10  # MB
    file_keep: int = 5
    colors: bool = True
    format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

@dataclass
class AutoDiscoveryConfig:
    enabled: bool = False
    filters: list[str] = []  # Multiple glob patterns
    excludes: list[str] = [] # Multiple glob patterns
    source: str | None = None  # Source type (e.g. "thermal"/"hwmon" for temperatures)
    device_ref: str | None = None  # Device template for auto-discovered items
    update_interval: float | None = None  # Override default interval
    options: dict[str, Any] = {}  # Per-metric overrides (e.g. rate on)
    
    def matches(name: str) -> bool  # Check if name matches filters/excludes
    def bool_override(name: str) -> bool | None  # Get boolean override for a metric

@dataclass
class Config:
    mqtt: MQTTConfig
    homeassistant: HomeAssistantConfig
    defaults: DefaultsConfig
    logging: LoggingConfig
    auto_refresh_interval: float = 0  # Top-level setting (0 = disabled)
    
    # Auto-discovery configs (parsed from auto_discovery { ... } block)
    auto_temperatures: AutoDiscoveryConfig
    auto_batteries: AutoDiscoveryConfig
    auto_containers: AutoDiscoveryConfig
    auto_services: AutoDiscoveryConfig
    auto_processes: AutoDiscoveryConfig
    auto_disks: AutoDiscoveryConfig
    auto_ac_powers: AutoDiscoveryConfig
    auto_networks: AutoDiscoveryConfig
    auto_fans: AutoDiscoveryConfig
    
    # Manual collectors
    system: list[SystemConfig]
    processes: list[ProcessConfig]
    services: list[ServiceConfig]
    containers: list[ContainerConfig]
    temperatures: list[TemperatureConfig]
    batteries: list[BatteryConfig]
    disks: list[DiskConfig]
    networks: list[NetworkConfig]
    ac_power: list[ACPowerConfig]
    fans: list[FanConfig]
    custom: list[CustomSensorConfig]
    binary_sensors: list[CustomBinarySensorConfig]
    
    @classmethod
    def from_document(doc: ConfigDocument) -> Config
```

---

### `loader.py` - Configuration Loader

Loads and validates configuration files.

**Classes:**

#### `ConfigLoader`
```python
class ConfigLoader:
    def load_file(path: str | Path) -> Config
    def load_string(source: str, filename: str, base_path: Path) -> Config
    def validate(config: Config) -> list[str]  # Returns warnings
    def _check_unknown_directives(document, config) -> list[str]  # Warn about unknown directives
```

**Functions:**
- `load_config(path)` - Convenience function

**Validation:**
- Checks for unknown directives in configuration blocks
- Warns about missing required settings
- Validates auto-discovery filters (required for services/processes)

---

## Collectors Module (`collectors/`)

### `base.py` - Abstract Collector

Base classes for all collectors.

**Classes:**

#### `CollectorResult`
```python
@dataclass
class CollectorResult:
    data: dict[str, Any] = {}        # JSON data dict (key -> value)
    state: str = "online"             # Source state (online/running/active/not_found)
    available: bool = True
    error: str | None = None
    timestamp: datetime
    
    def set(key: str, value: Any) -> None
    def set_state(state: str) -> None
    def set_unavailable(state: str = "not_found") -> None
    def set_error(error: str) -> None
    def to_json_dict() -> dict[str, Any]
```

#### `Collector` (Abstract)
```python
class Collector(ABC):
    SOURCE_TYPE: str = "unknown"  # Class attribute: system, process, service, etc.
    
    def __init__(self, name, collector_id, update_interval, enabled)
    
    # Properties
    @property
    def device(self) -> Device | None
    @property
    def sensors(self) -> list[Sensor]
    @property
    def availability(self) -> SensorState
    
    # Abstract methods (must implement)
    @abstractmethod
    def create_device(self) -> Device
    
    @abstractmethod
    def create_sensors(self) -> list[Sensor]
    
    @abstractmethod
    async def collect(self) -> CollectorResult
    
    # Public methods
    async def initialize() -> None
    async def safe_collect() -> CollectorResult  # With error handling
    async def run_forever() -> AsyncIterator[CollectorResult]
    
    # Topic helpers
    def sensor_id(metric: str) -> str  # Generate unique_id for metric
    def source_topic(topic_prefix: str) -> str  # Get JSON topic for source
    
    # Helpers
    def get_sensor(unique_id: str) -> Sensor | None
    @staticmethod
    def _sanitize_id(value: str) -> str
```

#### `MultiSourceCollector` (Abstract)
For collectors that monitor multiple sources (processes, containers).

```python
class MultiSourceCollector(Collector):
    def __init__(..., aggregate: bool = False)
    
    @abstractmethod
    async def discover_sources(self) -> list[Any]
    
    @abstractmethod
    async def collect_from_source(source: Any) -> CollectorResult
    
    async def collect(self) -> CollectorResult  # Discovers and collects
    async def _collect_aggregated(sources) -> CollectorResult
```

---

### `system.py` - System Collector

Collects system-wide metrics using psutil.

**Class: `SystemCollector`**

Topic: `{prefix}/system` → JSON with all metrics

Metrics (configurable via system block):
- `kernel_version` - Kernel release (always collected)
- `cpu_percent` - Overall CPU usage (%)
- `cpu{N}_percent` - Per-core CPU usage (%)
- `memory_percent`, `memory_used`, `memory_total` - RAM (MiB)
- `swap_percent`, `swap_used`, `swap_total` - Swap (MiB)
- `load_1m`, `load_5m`, `load_15m` - Load average
- `uptime` - System uptime (seconds)
- `disk_read`, `disk_write` - System disk I/O totals (bytes; `disk_io`)
- `disk_read_rate`, `disk_write_rate` - Disk I/O rate (KiB/s; `disk_io_rate`)
- `cpu_freq_current`, `cpu_freq_min`, `cpu_freq_max` - CPU frequency (MHz; N/A on some platforms)
- `process_count_total`, `process_count_running` - Process counts
- `boot_time` - Boot time (ISO timestamp for HA)

Note: System collector has no `state` field - uses global `{prefix}/status` for availability

---

### `temperature.py` - Temperature Collector

Reads temperatures from thermal zones and hwmon.

**Functions:**
- `discover_thermal_zones()` - Find thermal zones in sysfs
- `discover_hwmon_sensors()` - Find hwmon temperature sensors via psutil
- `read_thermal_zone_temp(zone)` - Read temperature

**Class: `TemperatureCollector`**

Metrics per sensor:
- `temp` - Temperature (°C)
- `state` - online/not_found (sensor availability)

Topic: `{prefix}/temperature/{sensor_name}` → JSON: `{"temp": 42.0, "state": "online"}`

---

### `process.py` - Process Collector

Monitors processes with various matching strategies.

**Functions:**
- `find_processes_by_name(name)` - Match by comm
- `find_processes_by_pattern(pattern)` - Match by regex on cmdline
- `find_process_by_pid(pid)` - Exact PID
- `find_process_by_pidfile(pidfile)` - Read PID from file
- `find_processes_by_cmdline(substring)` - Substring in cmdline

**Class: `ProcessCollector` (extends MultiSourceCollector)**

Metrics:
- `state` - Source state: `running` (process(es) found and metrics collected), `not_found` (no matching processes), `error` (e.g. access denied)
- `count` - Number of matched processes (if aggregate)
- `cpu_percent` - CPU usage (%, normalized to 0-100%)
- `memory_rss` - RSS memory (MB)
- `memory_percent` - Memory usage (%)
- `memory_pss` - Real PSS memory (MB, excludes file-backed mappings, requires smaps)
- `memory_uss` - Real USS memory (MB, excludes file-backed mappings, requires smaps)
- `io_read`, `io_write` - I/O bytes (MB)
- `num_fds` - Open file descriptors
- `num_threads` - Thread count

---

### `service.py` - Systemd Service Collector

Monitors systemd services using systemctl and cgroups.

**Async Functions:**
- `run_systemctl(*args)` - Execute systemctl command
- `get_service_property(unit, prop)` - Get service property
- `get_service_state(unit)` - Get active state
- `get_service_main_pid(unit)` - Get MainPID
- `get_service_restart_count(unit)` - Get NRestarts
- `list_units(pattern)` - List matching units

**Class: `ServiceCollector`**

Metrics:
- `state` - systemd ActiveState: `active`, `inactive`, `failed`, `activating`, `deactivating`, `reloading`; or `not_found` (unit missing), `unknown` (property unreadable)
- `restarts` - Restart count
- `cpu_percent` - CPU usage (%, normalized to 0-100%, delta-based from cgroup)
- `memory` - Memory Cgroup (MiB, includes cache - use PSS/USS for accurate RAM usage)
- `memory_cache` - Cache memory (MB)
- `memory_pss` - Real PSS memory (MB, excludes file-backed mappings, if smaps enabled)
- `memory_uss` - Real USS memory (MB, excludes file-backed mappings, if smaps enabled)
- `processes` - Number of processes in service

---

### `container.py` - Docker Container Collector

Monitors Docker containers via API.

**Class: `ContainerCollector`**

Metrics:
- `state` - Docker container state: `running`, `exited`, `paused`, `restarting`, `dead`, `created`, `removing`; or `not_found` (container missing), `unknown` (API did not return state)
- `health` - healthy/unhealthy/starting (if available)
- `cpu_percent` - CPU usage (%, normalized to 0-100%)
- `memory_usage` - Memory (MB)
- `memory_percent` - Memory (%)
- `memory_limit` - Memory limit (MB)
- `network_rx`, `network_tx` - Network I/O (MB)
- `disk_read`, `disk_write` - Block I/O (MB)
- `uptime` - Container uptime (seconds)
- `pids` - Process count

---

### `battery.py` - Battery Collector

Reads battery status from `/sys/class/power_supply/`.

**Functions:**
- `discover_batteries()` - Find battery devices
- `read_sysfs_value(path)` - Read string from sysfs
- `read_sysfs_int(path)` - Read integer from sysfs
- `read_sysfs_float(path, scale)` - Read float with scaling

**Class: `BatteryCollector`**

Metrics:
- `state` - charging/discharging/full/not charging/not_found
- `capacity` - Charge level (%)
- `voltage` - Current voltage (V)
- `current` - Current (A)
- `power` - Power consumption (W)
- `health` - Battery health
- `cycles` - Charge cycle count
- `temperature` - Battery temperature (°C)
- `time_to_empty` - Minutes remaining
- `time_to_full` - Minutes to full charge
- `energy_now`, `energy_full`, `energy_full_design` - Energy (Wh)
- `charge_full_design` - Design full charge (mAh)
- `present` - Presence flag (0/1)
- `technology` - Chemistry (e.g., Li-ion)
- `voltage_max`, `voltage_min` - Current voltage limits (V)
- `voltage_max_design`, `voltage_min_design` - Design voltage limits (V)
- `constant_charge_current`, `constant_charge_current_max` - Charge currents (A)
- `charge_full_design` - Design full charge (mAh)

---

### `disk.py` - Disk Collector

Reads disk space from mounted partitions via psutil.

**Functions:**
- `discover_disks()` - Find mounted block device partitions
- `get_disk_by_name(name)` - Find disk by device name (sda1, nvme0n1p1)
- `get_disk_by_mountpoint(mountpoint)` - Find disk by mountpoint
- `get_disk_by_uuid(uuid)` - Find disk by UUID (resolves /dev/disk/by-uuid/ symlink)

**Class: `DiskCollector`**

Metrics:
- `state` - online/not_found
- `total` - Total size (GB)
- `used` - Used space (GB)
- `free` - Free space (GB)
- `percent` - Usage percentage (%)

Topic: `{prefix}/disk/{name}` → JSON: `{"total": 100.0, "used": 50.0, "free": 50.0, "percent": 50.0, "state": "online"}`

---

### `ac_power.py` - AC Power Collector

Monitors external power supplies (non-battery) from `/sys/class/power_supply/`.

**Functions:**
- `discover_ac_power()` - Find non-battery power supplies (mains/USB/etc.)
- `read_online(path)` - Read `online` attribute (1 = connected, 0 = disconnected)

**Class: `ACPowerCollector`**

Metrics:
- `state` - online/not_found (source availability: "online" if data read successfully, "not_found" if source unavailable)
- `online` - boolean: `true` if external power is present, `false` otherwise

Topic: `{prefix}/ac_power/{name}` → JSON: `{"online": true, "state": "online"}`.
Exposed to Home Assistant as a `binary_sensor` with `ON`/`OFF` derived from `online`.

---

### `network.py` - Network Interface Collector

Monitors network interfaces via `psutil.net_io_counters(pernic=True)` and `psutil.net_if_stats()`.

**Functions:**
- `discover_network_interfaces()` - List interface names (e.g. eth0, wlan0)

**Class: `NetworkCollector`**

Metrics (all configurable via config/defaults):
- `bytes_sent`, `bytes_recv` - Total bytes
- `packets_sent`, `packets_recv` - Packet counts
- `errin`, `errout` - Error counts
- `dropin`, `dropout` - Dropped packet counts
- `bytes_sent_rate`, `bytes_recv_rate` - Rate (KiB/s) when `rate on`
- `packets_sent_rate`, `packets_recv_rate` - Packet rate when `packets_rate on`
- `isup` - Interface up/down (boolean, binary_sensor in HA)
- `speed` - Link speed (Mbps), `mtu`, `duplex`
- `state` - online/not_found (source availability)

Topic: `{prefix}/network/{name}` → JSON with above fields. Default device: system.
Optional `rssi on`: Wi-Fi signal strength (dBm) via `iw dev <iface> link` or `iwconfig`.

---

### `fan.py` - Fan (RPM) Collector

Reads fan speed from `/sys/class/hwmon/hwmon*/fan*_input` (RPM). One collector per hwmon; reports `fan1_rpm`, `fan2_rpm`, or `rpm` (single fan).

**Functions:**
- `discover_fan_hwmons()` - List (hwmon_basename, display_name, list of FanInput)

**Class: `FanCollector`**

Metrics: `fan{N}_rpm` or `rpm` (unit RPM). Supports manual `fan "name" { hwmon "hwmon0"; }` and auto-discovery via `auto_discovery { fans { auto on; } }`.

Topic: `{prefix}/fan/{name}` → JSON with fan metrics. Default device: system.

---

### `custom.py` - Custom Command Collector

Executes user-defined commands.

**Class: `CustomCollector`**

Methods:
- `_execute_command()` - Run command with timeout
- `_parse_output(output)` - Parse based on type (number/string/json)

Metrics:
- `state` - online/error/not_found
- `value` - Parsed command output

---

### `custom_binary.py` - Custom Binary Sensor Collector

Executes user-defined commands and interprets results as ON/OFF states.

**Class: `CustomBinarySensorCollector`**

Methods:
- `_execute_command()` - Run command with timeout
- `_parse_binary_value(returncode, output)` - Parse as ON/OFF based on value_source

Metrics:
- `state` - "ON" or "OFF" (always "online" availability)

Value sources:
- `returncode`: 0 = ON, non-zero = OFF
- `output`: Parse stdout for ON/OFF patterns

---

### `gpu.py` - GPU Collector

Reads GPU metrics from sysfs (minimal implementation).

**Functions:**
- `discover_gpu_devices()` - Find GPUs (devfreq, drm)
- `get_devfreq_metrics(device)` - Metrics from devfreq
- `get_drm_metrics(device)` - Metrics from DRM

**Class: `GPUCollector`**

Metrics (primary GPU):
- `state` - online/not_found
- `frequency` - GPU frequency (MHz)
- `temperature` - GPU temperature (°C)
- `utilization` - GPU utilization (%)

---

## MQTT Module (`mqtt/`)

### `client.py` - MQTT Client

Async MQTT client with reconnection support.

**Class: `MQTTClient`**

```python
class MQTTClient:
    def __init__(self, config: MQTTConfig, availability_topic: str)
    
    # Properties
    @property
    def connected(self) -> bool
    @property
    def topic_prefix(self) -> str
    
    # Connection
    async def connect() -> None
    async def disconnect() -> None
    
    # Publishing
    async def publish(topic, payload, qos, retain) -> None
    async def publish_json(topic, data, qos, retain) -> None  # Publish JSON dict
    
    # Lifecycle
    async def start() -> None               # Start background publisher
    async def stop() -> None                # Stop and disconnect
    async def session() -> AsyncContextManager  # Context manager
    async def wait_connected(timeout) -> bool
```

**Topic Structure:**
- `{prefix}/system` → JSON: `{"cpu_percent": 75.5, "memory_percent": 45.2, ...}`
- `{prefix}/temperature/{sensor}` → JSON: `{"temp": 42.0, "state": "online"}`
- `{prefix}/process/{name}` → JSON: `{"cpu_percent": 2.5, "state": "running", ...}`
- `{prefix}/service/{name}` → JSON: `{"cpu_percent": 1.2, "state": "active", ...}`
- `{prefix}/docker/{name}` → JSON: `{"cpu_percent": 5.0, "state": "running", ...}`
- `{prefix}/status` → `"online"` or `"offline"` (global availability)

Features:
- Auto-reconnection with exponential backoff
- Last Will and Testament (LWT) for availability (`{prefix}/status` → `"offline"`)
- Message queue for offline buffering
- Background publisher task
- JSON payloads per source (single topic per source)
- Graceful shutdown: publishes `{"state": "offline"}` to all source topics when stopping

---

### `homeassistant.py` - HA Discovery

Home Assistant MQTT Discovery integration.

**Class: `HomeAssistantDiscovery`**

```python
class HomeAssistantDiscovery:
    def __init__(self, mqtt_client, config: HomeAssistantConfig)
    
    async def register_sensors(sensors: list[Sensor]) -> None
    async def finalize_registration() -> None  # Cleanup stale sensors
    async def _remove_stale_sensor(unique_id: str) -> None
```

**Features:**
- Automatic sensor registration via MQTT Discovery
- Dual availability mode: `availability_mode: "all"` with two conditions:
  1. Global status topic (`{prefix}/status`) - online/offline
  2. Local state in JSON with value_template mapping states to online/offline
- State file persistence for stale sensor cleanup
- JSON value templates for extracting metrics from source topics

**Availability Mapping:**
- `service`: `active` → online, else → offline
- `docker`: `running` → online, else → offline
- `process`: `running` → online, else → offline
- `temperature/battery/ac_power/custom`: `online` → online, else → offline
- `system`: Uses only global status (no local state field)

---

## Models Module (`models/`)

### `device.py` - HA Device Model

**Class: `Device`**

```python
@dataclass
class Device:
    identifiers: list[str]
    name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    hw_version: str | None = None
    sw_version: str | None = None
    suggested_area: str | None = None
    configuration_url: str | None = None
    via_device: str | None = None
    
    @property
    def primary_identifier(self) -> str
    
    def to_discovery_dict() -> dict[str, Any]
    def with_identifier_prefix(prefix: str) -> Device
    
    @staticmethod
    def _sanitize_id(value: str) -> str
```

**Functions:**
- `create_device(source_type, source_name, ...)` - Factory function

---

### `sensor.py` - HA Sensor Model

**Enums:**
- `SensorState`: `ONLINE`, `OFFLINE`, `UNKNOWN`
- `DeviceClass`: `TEMPERATURE`, `BATTERY`, `POWER`, `VOLTAGE`, etc.
- `StateClass`: `MEASUREMENT`, `TOTAL`, `TOTAL_INCREASING`

**Class: `Sensor`**

```python
@dataclass
class Sensor:
    unique_id: str
    name: str
    state_topic: str = ""  # JSON topic for source
    availability_topic: str | None = None
    device: Device | None = None
    
    # Configuration
    value_template: str | None = None  # e.g., "{{ value_json.cpu_percent }}"
    unit_of_measurement: str | None = None
    device_class: DeviceClass | str | None = None
    state_class: StateClass | str | None = None
    icon: str | None = None
    enabled_by_default: bool = True
    entity_category: str | None = None
    
    # Availability
    payload_available: str = "online"
    payload_not_available: str = "offline"
    
    # Properties
    @property
    def state(self) -> Any
    @state.setter
    def state(self, value: Any)
    
    @property
    def availability(self) -> SensorState
    
    # Methods
    def set_unavailable() -> None
    def to_discovery_dict(topic_prefix) -> dict[str, Any]
    def get_discovery_topic(prefix) -> str
```

**Functions:**
- `create_sensor(source_type, source_name, metric_name, ...)` - Factory function
  - Creates sensor with JSON value_template
  - Sets up dual availability (global status + local state) for non-system sources

---

## Utils Module (`utils/`)

### `smaps.py` - Memory Parser

Parses `/proc/PID/smaps` for detailed memory metrics.

**Class: `SmapsInfo`**

```python
@dataclass
class SmapsInfo:
    pss: int = 0              # Proportional Set Size
    uss: int = 0              # Unique Set Size
    rss: int = 0              # Resident Set Size
    swap: int = 0             # Swapped memory
    swap_pss: int = 0         # Proportional swap
    
    shared_clean: int = 0
    shared_dirty: int = 0
    private_clean: int = 0
    private_dirty: int = 0
    referenced: int = 0
    anonymous: int = 0
    size: int = 0
    
    # PSS breakdown (from smaps_rollup)
    pss_anon: int = 0         # PSS for anonymous memory
    pss_file: int = 0         # PSS for file-backed mappings
    pss_shmem: int = 0        # PSS for shared memory
    
    @property
    def shared(self) -> int
    @property
    def private(self) -> int
    @property
    def pss_mb(self) -> float
    @property
    def uss_mb(self) -> float
    @property
    def rss_mb(self) -> float
    @property
    def swap_mb(self) -> float
    @property
    def memory_real_pss_mb(self) -> float  # Pss_Anon + Pss_Shm + SwapPss (excludes file-backed)
    @property
    def memory_real_uss_mb(self) -> float  # Anonymous only (excludes file-backed)
    
    def __add__(self, other) -> SmapsInfo  # For aggregation
    def to_dict() -> dict[str, int | float]
```

**Functions:**
- `parse_smaps(pid)` - Parse full smaps file
- `parse_smaps_rollup(pid)` - Parse smaps_rollup (provides Pss_Anon, Pss_Shm breakdown)
- `get_process_memory(pid, use_rollup=False)` - Get memory info
  - Tries smaps_rollup first for breakdown, falls back to full smaps
  - Uses full smaps by default for accuracy
- `aggregate_smaps(pids)` - Aggregate multiple processes
- `iter_all_smaps()` - Iterate all accessible processes

**Memory Metrics:**
- `memory_real_pss` = `Pss_Anon + Pss_Shm + SwapPss` (excludes file-backed mappings)
- `memory_real_uss` = `Anonymous` (excludes file-backed mappings)
- These metrics give accurate RAM usage for processes that map large files (e.g., qbittorrent)

---

### `cgroup.py` - Cgroup Reader

Reads CPU/memory metrics from cgroups (v1 and v2).

**Class: `CgroupStats`**

```python
@dataclass
class CgroupStats:
    cpu_usage_usec: int = 0
    cpu_user_usec: int = 0
    cpu_system_usec: int = 0
    
    memory_current: int = 0
    memory_max: int = 0
    memory_swap: int = 0
    memory_cache: int = 0
    memory_rss: int = 0
    
    pids_current: int = 0
    
    @property
    def memory_mb(self) -> float
    @property
    def cpu_usage_sec(self) -> float
```

**Functions:**
- `detect_cgroup_version()` - Returns 1, 2, or 0
- `get_process_cgroup(pid)` - Get cgroup path for process
- `get_cgroup_stats(cgroup_path)` - Get stats (auto-detect version)
- `get_cgroup_stats_v1(cgroup_path)` - cgroup v1 specific
- `get_cgroup_stats_v2(cgroup_path)` - cgroup v2 specific
- `get_systemd_service_cgroup(unit_name)` - Get cgroup for service
- `get_cgroup_pids(cgroup_path)` - List PIDs in cgroup
- `iter_cgroup_children(cgroup_path)` - Iterate child cgroups

---

### `docker_api.py` - Docker API Client

Async Docker API client via Unix socket.

**Classes:**

#### `ContainerInfo`
```python
@dataclass
class ContainerInfo:
    id: str
    name: str
    image: str
    state: str
    status: str
    created: int = 0
    started_at: str = ""
    health: str | None = None
    labels: dict[str, str]
    
    @property
    def short_id(self) -> str
    @property
    def is_running(self) -> bool
```

#### `ContainerStats`
```python
@dataclass
class ContainerStats:
    cpu_percent: float = 0.0
    cpu_system: int = 0
    cpu_total: int = 0
    
    memory_usage: int = 0
    memory_limit: int = 0
    memory_percent: float = 0.0
    memory_cache: int = 0
    
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    
    block_read: int = 0
    block_write: int = 0
    
    pids: int = 0
    
    @property
    def memory_usage_mb(self) -> float
    @property
    def memory_limit_mb(self) -> float
```

#### `DockerClient`
```python
class DockerClient:
    def __init__(self, socket_path: str = "/var/run/docker.sock")
    
    @property
    def available(self) -> bool  # Socket exists?
    
    async def ping() -> bool
    async def list_containers(all, filters) -> list[ContainerInfo]
    async def get_container(container_id) -> ContainerInfo | None
    async def get_stats(container_id, stream) -> ContainerStats
    
    # Internal
    async def _request(method, path, query) -> tuple[int, dict, bytes]
    async def _get_json(path, query) -> Any
    def _decode_chunked(data: bytes) -> bytes
```

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        Configuration                             │
│  config.conf → Lexer → Parser → Schema → Config object          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Application                               │
│  Application creates collectors based on Config                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Collectors                                │
│  Each collector runs in async loop:                              │
│  1. Discover sources (processes, containers, etc.)               │
│  2. Collect metrics into CollectorResult.data dict               │
│  3. Return CollectorResult with JSON data                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        MQTT Publishing                           │
│  1. Register sensors via HA Discovery (with value_template)     │
│  2. Publish JSON payload to source topic (one per source)        │
│  3. Auto-refresh: periodically check for new/removed sources    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Home Assistant                            │
│  1. Receives discovery messages                                  │
│  2. Creates sensor entities                                      │
│  3. Updates state from MQTT                                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Auto-Discovery

Unified auto-discovery system for temperatures, batteries, AC power supplies, containers, services, processes, and disks.

**Configuration:**

All auto-discovery settings are grouped inside the `auto_discovery { }` block:

```nginx
auto_discovery {
    temperatures {
        auto on;
        filter "nvme_*";
        filter "soc_*";
        exclude "internal*";
    }

    containers {
        auto on;
        filter "myapp-*";
    }

    services {
        auto on;
        filter "docker*";  # Required for services/processes
    }

    processes {
        auto on;
        filter "python*";  # Required for processes
    }

    disks {
        auto on;
        filter "*";  # All partitions
    }

    ac_powers {
        auto on;
        # filter "axp*";
    }

    networks {
        auto on;
        # filter "eth*";
    }
}
```

**Features:**
- Multiple `filter` patterns (glob matching)
- Multiple `exclude` patterns
- Per-source-type defaults applied to auto-discovered items
- Boolean flags inside auto blocks override per-source defaults (e.g., `batteries { current off; temperature on; }`)
- `update_interval` inside an auto block overrides the interval for those auto-created collectors only
- Auto-refresh: periodically checks for new/removed sources (if `auto_refresh_interval > 0`)

**Auto-Refresh:**
- Runs every `auto_refresh_interval` seconds (0 = disabled)
- Automatically adds new sources matching filters
- Automatically removes disappeared sources
- Updates Home Assistant sensors dynamically

---

## Error Handling

1. **Configuration errors** - Raised during parsing, includes line/column info
2. **Collector errors** - Caught in `safe_collect()`, sets `result.error`
3. **MQTT errors** - Auto-reconnect with exponential backoff
4. **Source not found** - Reported via sensor state (`not_found`)
5. **Permission errors** - Logged, collector continues without affected metrics

---

## Extending

### Adding a new collector

1. Create new file in `collectors/`
2. Inherit from `Collector` or `MultiSourceCollector`
3. Set `SOURCE_TYPE` class attribute (e.g., `SOURCE_TYPE = "mytype"`)
4. Implement `create_device()`, `create_sensors()`, `collect()`
5. Return `CollectorResult` with `data` dict and `state` field
6. Use `result.set(key, value)` to add metrics
7. Use `result.set_state(state)` to set source state
8. Add config class to `schema.py`
9. Register in `app.py._create_collectors()`
10. Update `create_sensor()` to use `source_type` and `source_name` for topic structure

### Adding a new config block

1. Add dataclass to `schema.py`
2. Add `from_block()` class method
3. Add to `Config.from_document()`
4. Update `ConfigLoader.validate()`

