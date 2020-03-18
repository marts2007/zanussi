# ZANUSSI Home Assistant component
Currently works with ZACS/I-09 HV/A18/N1 (BroadLink_OEM wifi module)<br>
put zanussi folder to config/custom_components/ <br>
add configuration option to configuration.yaml

```climate:
  - platform: zanussi
    name: Some name here
    unique_id: some_uniq_name
    host: ip_address_here
    temperature_sensor: some_external_temp_sensor
    device_code: 0 
```

Based on SmartIR project https://github.com/smartHomeHub/SmartIR<br>

