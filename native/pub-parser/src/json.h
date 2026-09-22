// Minimal, deterministic JSON writer.
//
// Deliberately not a parser and not a dependency: the parser bundle has to
// be byte-for-byte reproducible across runs and machines, which rules out
// any container with unspecified iteration order. Objects therefore keep
// insertion order, and numbers go through one shared formatter.
#ifndef PUBIR_JSON_H
#define PUBIR_JSON_H

#include <string>
#include <utility>
#include <vector>

namespace pubir {

class Json {
public:
  enum class Kind { Null, Bool, Int, Double, String, Array, Object };

  Json() : kind_(Kind::Null) {}

  static Json null() { return Json(); }
  static Json boolean(bool v);
  static Json integer(long long v);
  static Json number(double v);
  static Json string(std::string v);
  static Json array();
  static Json object();

  Kind kind() const { return kind_; }
  bool isNull() const { return kind_ == Kind::Null; }

  // Object mutation. Re-setting an existing key overwrites in place, so the
  // key keeps its original position and the output stays stable.
  Json &set(const std::string &key, Json value);
  // Array mutation.
  Json &push(Json value);

  bool empty() const { return items_.empty(); }
  std::size_t size() const { return items_.size(); }

  std::string dump(int indent = 2) const;

  // Formats a double the way every number in the bundle is formatted:
  // integral values without a decimal point, everything else trimmed to at
  // most six decimal places. Exposed for tests.
  static std::string formatDouble(double v);
  static std::string escape(const std::string &s);

private:
  void dumpTo(std::string &out, int indent, int depth) const;

  Kind kind_;
  bool bool_ = false;
  long long int_ = 0;
  double double_ = 0.0;
  std::string string_;
  std::vector<std::pair<std::string, Json>> items_;
};

} // namespace pubir

#endif
