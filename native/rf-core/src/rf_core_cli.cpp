#include "rf_core.hpp"

#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

std::vector<double> parse_pfl_values(const std::string& csv) {
  std::vector<double> values;
  std::stringstream input(csv);
  std::string token;
  while (std::getline(input, token, ',')) {
    std::stringstream token_stream(token);
    double value = 0.0;
    token_stream >> value;
    if (token_stream.fail()) {
      throw std::runtime_error("Invalid PFL value: " + token);
    }
    values.push_back(value);
  }

  if (values.size() < 4) {
    throw std::runtime_error("PFL must contain count, spacing, and at least two elevation points");
  }
  const auto declared_intervals = static_cast<std::size_t>(values[0]);
  if (values.size() != declared_intervals + 3) {
    throw std::runtime_error("PFL point count does not match elevation value count");
  }
  return values;
}

void write_result(const rfcore::PathLossResult& result, const rfcore::ItmTlsParams& params,
                  const std::string& fixture) {
  std::cout << std::fixed << std::setprecision(6)
            << "{"
            << "\"engine\":\"" << result.engine << "\","
            << "\"fixture\":\"" << fixture << "\","
            << "\"frequency_mhz\":" << params.frequency_mhz << ","
            << "\"tx_height_m\":" << params.tx_height_m << ","
            << "\"rx_height_m\":" << params.rx_height_m << ","
            << "\"error_code\":" << result.error_code << ","
            << "\"warnings\":" << result.warnings << ","
            << "\"path_loss_db\":" << result.path_loss_db
            << "}" << std::endl;
}

int run_batch(int argc, char** argv) {
  rfcore::ItmTlsParams params;
  for (int index = 2; index < argc; ++index) {
    const std::string arg = argv[index];
    auto require_value = [&](const std::string& name) -> std::string {
      if (index + 1 >= argc) {
        throw std::runtime_error("Missing value for " + name);
      }
      return argv[++index];
    };

    if (arg == "--freq-mhz") {
      params.frequency_mhz = std::stod(require_value(arg));
    } else if (arg == "--location-pct") {
      params.location_percent = std::stod(require_value(arg));
    } else if (arg == "--time-pct") {
      params.time_percent = std::stod(require_value(arg));
    } else if (arg == "--situation-pct") {
      params.situation_percent = std::stod(require_value(arg));
    } else if (arg == "--climate") {
      params.climate = std::stoi(require_value(arg));
    } else if (arg == "--polarisation") {
      params.polarisation = std::stoi(require_value(arg));
    } else if (arg == "--surface-refractivity") {
      params.surface_refractivity_n_units = std::stod(require_value(arg));
    } else if (arg == "--ground-permittivity") {
      params.ground_permittivity = std::stod(require_value(arg));
    } else if (arg == "--ground-conductivity") {
      params.ground_conductivity_s_per_m = std::stod(require_value(arg));
    } else if (arg.rfind("--", 0) == 0) {
      throw std::runtime_error("Unknown batch option: " + arg);
    }
  }

  // Each line is tx-height|rx-height|PFL CSV. The process stays alive so
  // callers can evaluate many candidate-to-cell paths without process startup
  // and temporary-file overhead for every path.
  std::string line;
  while (std::getline(std::cin, line)) {
    try {
      const auto separator = line.find('|');
      const auto second_separator = line.find('|', separator == std::string::npos ? 0 : separator + 1);
      if (separator == std::string::npos || second_separator == std::string::npos) {
        throw std::runtime_error("Batch line must be tx-height|rx-height|PFL CSV");
      }
      params.tx_height_m = std::stod(line.substr(0, separator));
      params.rx_height_m = std::stod(
          line.substr(separator + 1, second_separator - separator - 1));
      const auto pfl = parse_pfl_values(line.substr(second_separator + 1));
      const auto result = rfcore::point_to_point_tls(pfl, params);
      write_result(result, params, "batch");
    } catch (const std::exception& error) {
      // Keep the protocol alive after a malformed path. The Python adapter
      // treats the missing path loss as an ITM failure and fails closed.
      std::cout << "{\"error\":\"" << error.what() << "\"}" << std::endl;
    }
  }
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  try {
    if (argc > 1 && std::string(argv[1]) == "--batch") {
      return run_batch(argc, argv);
    }

    rfcore::ItmTlsParams params;
    std::string pfl_path = "../../data/sample-region/golden-profiles/flat_1km.pfl.csv";

    for (int index = 1; index < argc; ++index) {
      const std::string arg = argv[index];
      auto require_value = [&](const std::string& name) -> std::string {
        if (index + 1 >= argc) {
          throw std::runtime_error("Missing value for " + name);
        }
        return argv[++index];
      };

      if (arg == "--freq-mhz") {
        params.frequency_mhz = std::stod(require_value(arg));
      } else if (arg == "--tx-height-m") {
        params.tx_height_m = std::stod(require_value(arg));
      } else if (arg == "--rx-height-m") {
        params.rx_height_m = std::stod(require_value(arg));
      } else if (arg == "--time-pct") {
        params.time_percent = std::stod(require_value(arg));
      } else if (arg == "--location-pct") {
        params.location_percent = std::stod(require_value(arg));
      } else if (arg == "--situation-pct") {
        params.situation_percent = std::stod(require_value(arg));
      } else if (arg == "--climate") {
        params.climate = std::stoi(require_value(arg));
      } else if (arg == "--polarisation") {
        params.polarisation = std::stoi(require_value(arg));
      } else if (arg == "--surface-refractivity") {
        params.surface_refractivity_n_units = std::stod(require_value(arg));
      } else if (arg == "--ground-permittivity") {
        params.ground_permittivity = std::stod(require_value(arg));
      } else if (arg == "--ground-conductivity") {
        params.ground_conductivity_s_per_m = std::stod(require_value(arg));
      } else if (arg.rfind("--", 0) == 0) {
        throw std::runtime_error("Unknown option: " + arg);
      } else {
        pfl_path = arg;
      }
    }

    const auto pfl = rfcore::parse_pfl_csv(pfl_path);
    const auto result = rfcore::point_to_point_tls(pfl, params);

    write_result(result, params, pfl_path);
    return result.error_code == 0 ? 0 : 2;
  } catch (const std::exception& error) {
    std::cerr << "rf_core_cli error: " << error.what() << std::endl;
    return 1;
  }
}
