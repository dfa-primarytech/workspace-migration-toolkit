# Build for the Publisher parser.
#
# Three targets, split so the unit tests never need libmspub: the callback
# sink is driven directly by synthetic property lists, which is what lets
# the model be tested without a .pub file on disk.
#
#   pubir             static library -- model, collector, serialisation
#   publisher-parser  CLI            -- adds libmspub and the stream reader
#   pubir-tests       unit tests     -- links pubir only
cmake_minimum_required(VERSION 3.16)
project(pub-parser CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

find_package(PkgConfig REQUIRED)
pkg_check_modules(REVENGE REQUIRED librevenge-0.0)
pkg_check_modules(REVENGE_STREAM REQUIRED librevenge-stream-0.0)
pkg_check_modules(MSPUB REQUIRED libmspub-0.1)

# The exact versions this build was tested against are recorded in
# docs/publisher-parser.md and reported by `publisher-parser --version`.
message(STATUS "librevenge ${REVENGE_VERSION}")
message(STATUS "libmspub ${MSPUB_VERSION}")

add_library(pubir STATIC
  src/collector.cpp
  src/image_info.cpp
  src/json.cpp
  src/serialise.cpp
  src/sha256.cpp
  src/units.cpp
)
target_include_directories(pubir PUBLIC src ${REVENGE_INCLUDE_DIRS})
target_link_libraries(pubir PUBLIC ${REVENGE_LIBRARIES})
target_link_directories(pubir PUBLIC ${REVENGE_LIBRARY_DIRS})

# Parsing untrusted input: keep the usual hardening on, and treat warnings
# as errors so a sloppy conversion does not reach a release build.
target_compile_options(pubir PRIVATE
  -Wall -Wextra -Wpedantic -Werror
  -fstack-protector-strong -D_FORTIFY_SOURCE=2
)

add_executable(publisher-parser src/bundle.cpp src/main.cpp)
target_link_libraries(publisher-parser PRIVATE
  pubir ${MSPUB_LIBRARIES} ${REVENGE_STREAM_LIBRARIES}
)
target_include_directories(publisher-parser PRIVATE
  ${MSPUB_INCLUDE_DIRS} ${REVENGE_STREAM_INCLUDE_DIRS}
)
target_link_directories(publisher-parser PRIVATE
  ${MSPUB_LIBRARY_DIRS} ${REVENGE_STREAM_LIBRARY_DIRS}
)
target_compile_definitions(publisher-parser PRIVATE
  PUBIR_LIBMSPUB_VERSION="${MSPUB_VERSION}"
  PUBIR_LIBREVENGE_VERSION="${REVENGE_VERSION}"
)
target_compile_options(publisher-parser PRIVATE
  -Wall -Wextra -Wpedantic -Werror
  -fstack-protector-strong -D_FORTIFY_SOURCE=2
)
target_link_options(publisher-parser PRIVATE -Wl,-z,relro -Wl,-z,now)

enable_testing()

add_executable(pubir-tests
  src/bundle.cpp
  tests/test_main.cpp
  tests/test_assets.cpp
  tests/test_bundle.cpp
  tests/test_collector.cpp
  tests/test_json.cpp
  tests/test_limits.cpp
  tests/test_sha256.cpp
  tests/test_tables.cpp
  tests/test_text.cpp
  tests/test_units.cpp
)
target_link_libraries(pubir-tests PRIVATE pubir)
target_include_directories(pubir-tests PRIVATE src tests)
target_compile_options(pubir-tests PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_test(NAME pubir-tests COMMAND pubir-tests)
