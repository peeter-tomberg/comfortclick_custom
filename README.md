# Notice

This is a custom component that works only with a specific comfort click integration.
You will most probably need to fork this for your own use case.

# Why

Wanted to control comfort click from home assistant.

# Whats in this

Integrated a wide range of different entities:

* Platform.CLIMATE
* Platform.LOCK
* Platform.FAN
* Platform.SENSOR
* Platform.SELECT

## Configuration

They are all configurable from '/custom_components/comfortclick_custom/config' folder through yaml files:

### fans.yaml

```yaml
fans:
  - name: "Bedroom fan"
    lock_id: ""
    fan_id: ""
    heating_id: ""
  - name: "Living room fan"
    lock_id: ""
    fan_id: ""
    heating_id: ""
```

### locks.yaml

```yaml
locks:
  - door_name: "Main door"
    door_id: ""
  - door_name: "Cellar door"
    door_id: ""
```

### thermostats.yaml

```yaml
thermostats:
  - name: "Bedroom AC"
    heating_id: ""
    fan_id: ""
    current_temperature_id: ""
    target_temperature_id: ""
  - name: "Living room AC"
    heating_id: ""
    fan_id: ""
    current_temperature_id: ""
    target_temperature_id: ""
  - name: "Bathroom AC"
    heating_id: ""
    fan_id: ""
    current_temperature_id: ""
    target_temperature_id: ""
    max_temp: 28
```

### utilities.yaml

```yaml
utilities:
  - name: "Water (cold, total)"
    id: ""
    type: "water"
  - name: "Water (hot, total)"
    id: ""
    type: "water"
  - name: "Electricity (day, total)"
    id: ""
    type: "electricity"
  - name: "Electricity (night, total)"
    id: ""
    type: "electricity"
  - name: "Heating (total)"
    id: ""
    type: "heating"
```

### vent.yaml

```yaml
away_mode: ""
home_mode: ""
guest_mode: ""

away_vent_air_temp: ""
home_vent_air_temp: ""
guest_vent_air_temp: ""

vent_winter_mode: ""
```