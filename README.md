[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

![Project Maintenance][maintenance-shield]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

Api Wrapper for Kia/Hyundai API using async in python, this was inspired by [this guide](https://developers.home-assistant.io/docs/api_lib_index) to be a lightweight wrapper, with simple error handling.

a lot of this is a port of [Bluelinky](https://github.com/Hacksore/bluelinky) from node.

# US Kia

- login
- get_vehicles
- get_cached_vehicle_status
- request_vehicle_data_sync
- check_last_action_status - allows verification actions have completed on vehicle
- lock
- unlock
- start_climate
- stop_climate
- start_charge
- stop_charge
- set_charge_limits

# US Hyundai

- login
- get_vehicles
- get_cached_vehicle_status
- get_location
- lock
- unlock
- start_climate
- stop_climate

# CA Kia/Hyundai

- login
- get_vehicles
- get_cached_vehicle_status
- get_next_service_status
- get_pin_token
- get_location
- request_vehicle_data_sync
- check_last_action_status - allows verification actions have completed on vehicle
- lock
- unlock
- start_climate
- start_climate_ev
- stop_climate
- stop_climate_ev
- start_charge
- stop_charge
- set_charge_limits

***

[kia_hyundai_api]: https://github.com/dahlb/kia_hyundai_api
[commits-shield]: https://img.shields.io/github/commit-activity/y/dahlb/kia_hyundai_api.svg?style=for-the-badge
[commits]: https://github.com/dahlb/kia_hyundai_api/commits/main
[forum]: https://community.home-assistant.io/
[license-shield]: https://img.shields.io/github/license/dahlb/kia_hyundai_api.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-Bren%20Dahl%20%40dahlb-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/dahlb/kia_hyundai_api.svg?style=for-the-badge
[releases]: https://github.com/dahlb/kia_hyundai_api/releases
[buymecoffee]: https://www.buymeacoffee.com/dahlb
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
