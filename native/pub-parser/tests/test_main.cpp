#include "testing.h"

#include <exception>

namespace testing {

std::vector<TestCase> &registry() {
  static std::vector<TestCase> cases;
  return cases;
}

void fail(const std::string &where, const std::string &message) {
  throw Failure{where + ": " + message};
}

int runAll() {
  int failures = 0;
  for (const TestCase &test : registry()) {
    try {
      test.body();
      std::cout << "ok   " << test.name << "\n";
    } catch (const Failure &failure) {
      std::cout << "FAIL " << test.name << "\n       " << failure.message << "\n";
      failures++;
    } catch (const std::exception &error) {
      std::cout << "FAIL " << test.name << "\n       threw: " << error.what() << "\n";
      failures++;
    }
  }
  std::cout << "\n" << registry().size() - static_cast<std::size_t>(failures) << "/"
            << registry().size() << " tests passed\n";
  return failures == 0 ? 0 : 1;
}

} // namespace testing

int main() { return testing::runAll(); }
