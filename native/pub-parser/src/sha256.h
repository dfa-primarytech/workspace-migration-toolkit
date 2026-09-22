// SHA-256, self-contained.
//
// Assets are identified and deduplicated by content hash, so the parser
// needs a digest before it has decided anything else about a payload.
// Pulling OpenSSL in for one hash would add a linkage and a licence
// question to a binary that otherwise only needs libmspub.
#ifndef PUBIR_SHA256_H
#define PUBIR_SHA256_H

#include <cstddef>
#include <cstdint>
#include <string>

namespace pubir {

class Sha256 {
public:
  Sha256();
  void update(const unsigned char *data, std::size_t len);
  void update(const std::string &data);
  // Lowercase hex. Finalises a copy, so the object stays usable.
  std::string hex() const;

  static std::string of(const unsigned char *data, std::size_t len);
  static std::string of(const std::string &data);

private:
  void block(const unsigned char *p);

  uint32_t state_[8];
  uint64_t bits_;
  unsigned char buffer_[64];
  std::size_t bufferLen_;
};

} // namespace pubir

#endif
