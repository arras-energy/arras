# powerflow data files

Data files installed with the `powerflow` package. A class looks for its
file in the search path (`arras.folders.findfile()`: the working folder,
the user `share` folder, `GLPATH`) and then here, so a model can use its
own copy by naming it in the module global.

| File | Global | Used by | Source (gridlabd master 076e78a) |
| ---- | ------ | ------- | -------------------------------- |
| `naics_data_file.csv` | `powerflow::NAICS_datafile` | `industrial` | `module/industrial/naics_data_file.csv` |
| `building_defaults.csv` | `powerflow::building_defaults` | `building` | `module/powerflow/data/building_defaults.csv` |
| `building_loadshapes.csv` | `powerflow::building_loadshapes` | `building` | `module/powerflow/data/building_loadshapes.csv` |
| `building_occupancy.csv` | `powerflow::building_occupancy` | `building` | `module/powerflow/data/building_occupancy.csv` |
| `inverter_settings.csv` | `powerflow::inverter_settings` | `building` | `module/powerflow/data/inverter_settings.csv` |
| `ductbank_configurations.csv` | `powerflow::ductbank_configuration_file` | `ductbank` | `module/powerflow/data/ductbank_configurations.csv` |
