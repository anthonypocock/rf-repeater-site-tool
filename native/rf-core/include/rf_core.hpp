#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace rfcore {

struct ItmTlsParams {
  double tx_height_m = 10.0;
  double rx_height_m = 2.0;
  int climate = 5;
  double surface_refractivity_n_units = 301.0;
  double frequency_mhz = 150.0;
  int polarisation = 1;
  double ground_permittivity = 15.0;
  double ground_conductivity_s_per_m = 0.005;
  int variability_mode = 0;
  double time_percent = 50.0;
  double location_percent = 50.0;
  double situation_percent = 50.0;
};

struct PathLossResult {
  int error_code = 0;
  long warnings = 0;
  double path_loss_db = 0.0;
  std::string engine = "rf-core-ntia-itm";
};

std::vector<double> parse_pfl_csv(const std::string& path);
PathLossResult point_to_point_tls(const std::vector<double>& pfl, const ItmTlsParams& params);

}  // namespace rfcore

