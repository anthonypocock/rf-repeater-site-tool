#include "rf_core.hpp"

#include "itm.h"

#include <fstream>
#include <sstream>
#include <stdexcept>

namespace rfcore {

std::vector<double> parse_pfl_csv(const std::string& path) {
  std::ifstream input(path);
  if (!input) {
    throw std::runtime_error("Unable to open PFL file: " + path);
  }

  std::vector<double> values;
  std::string token;
  while (std::getline(input, token, ',')) {
    std::stringstream token_stream(token);
    double value = 0.0;
    token_stream >> value;
    if (!token_stream.fail()) {
      values.push_back(value);
    }
  }

  if (values.size() < 4) {
    throw std::runtime_error("PFL file must contain count, spacing, and at least two elevation points");
  }

  const auto declared_intervals = static_cast<std::size_t>(values[0]);
  const auto expected_values = declared_intervals + 3;
  if (values.size() != expected_values) {
    throw std::runtime_error("PFL point count does not match elevation value count");
  }

  return values;
}

PathLossResult point_to_point_tls(const std::vector<double>& pfl, const ItmTlsParams& params) {
  PathLossResult result;
  double path_loss_db = 0.0;
  long warnings = 0;

  const int error_code = ITM_P2P_TLS(
      params.tx_height_m,
      params.rx_height_m,
      pfl.data(),
      params.climate,
      params.surface_refractivity_n_units,
      params.frequency_mhz,
      params.polarisation,
      params.ground_permittivity,
      params.ground_conductivity_s_per_m,
      params.variability_mode,
      params.time_percent,
      params.location_percent,
      params.situation_percent,
      &path_loss_db,
      &warnings);

  result.error_code = error_code;
  result.warnings = warnings;
  result.path_loss_db = path_loss_db;
  return result;
}

}  // namespace rfcore

