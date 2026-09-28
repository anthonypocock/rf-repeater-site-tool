CXX ?= g++
NTIA_DIR := vendor/ntia-itm
BIN_DIR := bin
BUILD_DIR := build

CXXFLAGS := -std=c++17 -O2 -Wall -Wextra -D'__declspec(x)=' -Iinclude -I$(NTIA_DIR)/include
NTIA_SRC := $(wildcard $(NTIA_DIR)/src/*.cpp)
APP_SRC := src/rf_core.cpp src/rf_core_cli.cpp

.PHONY: build test clean vendor-check

vendor-check:
	@test -f "$(NTIA_DIR)/include/itm.h" || (echo "NTIA ITM source missing. Run make rf-core-vendor from the repository root."; exit 1)

build: vendor-check
	@mkdir -p $(BIN_DIR) $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(APP_SRC) $(NTIA_SRC) -o $(BIN_DIR)/rf_core_cli

test: build
	@mkdir -p $(BUILD_DIR)
	$(BIN_DIR)/rf_core_cli ../../data/sample-region/golden-profiles/flat_1km.pfl.csv > $(BUILD_DIR)/flat_1km.actual.json
	python3 tests/assert_fixture.py ../../data/sample-region/golden-profiles/flat_1km.expected.json $(BUILD_DIR)/flat_1km.actual.json

clean:
	rm -rf $(BIN_DIR) $(BUILD_DIR)

