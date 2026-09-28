.PHONY: test test-schemas api-test mvp-test rf-core-vendor rf-core-build rf-core-test run-mvp clean

test: test-schemas api-test rf-core-vendor rf-core-build rf-core-test mvp-test

test-schemas:
	python3 packages/schemas/tests/test_schema_files.py

api-test:
	python3 services/api/tests/test_job_runner.py
	python3 services/api/tests/test_analysis_jobs.py
	python3 services/api/tests/test_auth.py
	python3 services/api/tests/test_saved_results.py

mvp-test:
	python3 services/api/tests/test_mvp_analysis.py

rf-core-vendor:
	./native/rf-core/scripts/fetch_ntia_itm.sh

rf-core-build:
	$(MAKE) -C native/rf-core build

rf-core-test:
	$(MAKE) -C native/rf-core test

run-mvp:
	python3 services/api/mvp_server.py

clean:
	rm -rf native/rf-core/bin native/rf-core/build
