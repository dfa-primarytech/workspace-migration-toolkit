// A test runner in one header.
//
// gtest would mean either a system package that CI has to install or a
// vendored copy in the repository; neither is worth it for a binary whose
// only real dependency is libmspub. Tests register themselves at static
// initialisation time and the runner runs them all.
#ifndef PUBIR_TESTING_H
#define PUBIR_TESTING_H

#include <cmath>
#include <functional>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace testing {

struct TestCase {
  std::string name;
  std::function<void()> body;
};

std::vector<TestCase> &registry();
int runAll();

struct Registrar {
  Registrar(const char *name, std::function<void()> body) {
    registry().push_back({name, std::move(body)});
  }
};

struct Failure {
  std::string message;
};

void fail(const std::string &where, const std::string &message);

} // namespace testing

#define TEST(name)                                                                                 \
  static void name();                                                                              \
  static testing::Registrar name##_registrar(#name, name);                                         \
  static void name()

#define CHECK(condition)                                                                           \
  do {                                                                                             \
    if (!(condition)) {                                                                            \
      testing::fail(std::string(__FILE__) + ":" + std::to_string(__LINE__),                        \
                    "expected " #condition);                                                       \
    }                                                                                              \
  } while (false)

#define CHECK_EQ(actual, expected)                                                                 \
  do {                                                                                             \
    const auto &checkActual = (actual);                                                            \
    const auto &checkExpected = (expected);                                                        \
    if (!(checkActual == checkExpected)) {                                                         \
      std::ostringstream checkStream;                                                              \
      checkStream << "expected " #actual " == " #expected " but got [" << checkActual              \
                  << "] and [" << checkExpected << "]";                                            \
      testing::fail(std::string(__FILE__) + ":" + std::to_string(__LINE__), checkStream.str());    \
    }                                                                                              \
  } while (false)

#define CHECK_NEAR(actual, expected, tolerance)                                                    \
  do {                                                                                             \
    const double checkActual = static_cast<double>(actual);                                        \
    const double checkExpected = static_cast<double>(expected);                                    \
    if (std::fabs(checkActual - checkExpected) > (tolerance)) {                                    \
      std::ostringstream checkStream;                                                              \
      checkStream << "expected " #actual " ~= " << checkExpected << " but got " << checkActual;    \
      testing::fail(std::string(__FILE__) + ":" + std::to_string(__LINE__), checkStream.str());    \
    }                                                                                              \
  } while (false)

#endif
