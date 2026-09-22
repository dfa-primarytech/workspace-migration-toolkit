#include "testing.h"

#include "sha256.h"

#include <cstddef>
#include <string>
#include <vector>

using namespace pubir;

// Assets are deduplicated by digest, so a hashing bug would silently merge
// two different pictures or split one into two. The known-answer vectors in
// test_assets.cpp cover short inputs only; these cover the padding
// boundaries and streaming.
//
// Expected digests were produced by Python's hashlib, an independent
// implementation, over pattern(n) below.

namespace {

// Deterministic, non-repeating over one block, and not all one byte value,
// so a misplaced byte shows up in the digest.
std::string pattern(std::size_t n) {
  std::string out;
  out.reserve(n);
  for (std::size_t i = 0; i < n; i++) out += static_cast<char>((i * 31 + 7) & 0xff);
  return out;
}

struct Vector {
  std::size_t length;
  const char *digest;
};

// 55 is the longest message whose padding and length fit in one block; 56
// is the shortest that needs a second. 63/64/65 straddle a full block, and
// 119/120 and 127/128/129 repeat both boundaries one block further on.
const Vector kBoundaries[] = {
    {0, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
    {1, "ca358758f6d27e6cf45272937977a748fd88391db679ceda7dc7bf1f005ee879"},
    {55, "8aa994584139d128848eeebc4e815639ba5ab6e6e39574195a63ac4f14f7c43b"},
    {56, "ad574708f75c044c9b85de64cb568ee7711ff4f36448c6242f053ba8f6cc2b63"},
    {57, "5b46e502092be01b1100193e089fdda95638c12e19a1d24f308eb2c3d3ae849d"},
    {63, "280ed3e8ff1df845b2e7dfe6ac6cee817bef20e783cc65abc41b818b4d2fe076"},
    {64, "c6ab9724ade5b6a7a1edfffb12f3aa9181351355af8fd08c919952ad211339dd"},
    {65, "788367c73c7ddf4c53f65e68cc0d943e6227ab55b0e78ba63ace822b1c6301c0"},
    {119, "3d610547d68216dedf7435a4fb6260353911f6b3fd3f18805ddb8be285d726fe"},
    {120, "1f80156a804cb7862ad113e8200e9d74499723e7c7854d5f48776d3148e09656"},
    {127, "192409cd280e14b743642ad1343fbd3e82d9305de72c078117745a679210cc3d"},
    {128, "cc548ca2dec1f6fe4f58b2e27aa9c7521607df1130d140b55a4dad0665302356"},
    {129, "81e89a7b2911aaa7795f9e3d4910cb47d6cd2b00d83b8399481527261a1a7519"},
    {1000, "5097e7d587352f5097062ae679f37bda5802d9f875aba14c8cb4d1a188ada179"},
};

const unsigned char *bytes(const std::string &s) {
  return reinterpret_cast<const unsigned char *>(s.data());
}

// Feeds data in chunks whose sizes cycle through `sizes`, so chunk edges
// fall at a different offset within each block.
std::string streamed(const std::string &data, const std::vector<std::size_t> &sizes) {
  Sha256 h;
  std::size_t offset = 0;
  std::size_t next = 0;
  while (offset < data.size()) {
    std::size_t take = sizes[next++ % sizes.size()];
    if (take > data.size() - offset) take = data.size() - offset;
    h.update(bytes(data) + offset, take);
    offset += take;
  }
  return h.hex();
}

} // namespace

TEST(sha256_padding_boundaries_match_reference) {
  for (const Vector &v : kBoundaries) {
    CHECK_EQ(Sha256::of(pattern(v.length)), std::string(v.digest));
  }
}

TEST(sha256_nist_two_block_and_million_byte_vectors) {
  CHECK_EQ(Sha256::of(std::string("abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmn"
                                  "hijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu")),
           std::string("cf5b16a778af8380036ce59e7b0492370b249b11e8f07a51afac45037afee9d1"));

  // Streamed in uneven pieces: exercises the bit counter well past one
  // block and the buffer carrying partial blocks between calls.
  const std::string million(1000000, 'a');
  CHECK_EQ(streamed(million, {1, 4095, 64, 7}),
           std::string("cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0"));
}

TEST(sha256_uniform_chunk_sizes_match_one_shot) {
  const std::vector<std::size_t> chunkSizes = {1, 2, 3, 7, 13, 55, 56, 63, 64, 65, 127, 128};
  for (const Vector &v : kBoundaries) {
    const std::string data = pattern(v.length);
    for (std::size_t size : chunkSizes) {
      CHECK_EQ(streamed(data, {size}), std::string(v.digest));
    }
  }
}

TEST(sha256_uneven_streaming_matches_one_shot) {
  const std::vector<std::vector<std::size_t>> schedules = {
      {1, 2, 3, 5, 8, 13, 21, 34},
      {63, 1},
      {1, 63},
      {65, 3, 60},
      {55, 9, 64},
      {100, 1, 27},
  };
  for (const Vector &v : kBoundaries) {
    const std::string data = pattern(v.length);
    for (const auto &schedule : schedules) {
      CHECK_EQ(streamed(data, schedule), std::string(v.digest));
    }
  }
}

TEST(sha256_every_split_point_of_two_blocks) {
  // Two updates, split at every offset: catches an off-by-one in how the
  // buffer is topped up when a call starts mid-block.
  const std::string data = pattern(129);
  for (std::size_t split = 0; split <= data.size(); split++) {
    Sha256 h;
    h.update(bytes(data), split);
    h.update(bytes(data) + split, data.size() - split);
    CHECK_EQ(h.hex(), std::string(kBoundaries[12].digest));
  }
}

TEST(sha256_hex_does_not_disturb_a_running_hash) {
  // hex() finalises a copy; calling it mid-stream must leave the object
  // able to continue as though it had never been called.
  const std::string data = pattern(129);
  Sha256 h;
  h.update(bytes(data), 60);
  CHECK_EQ(h.hex(), Sha256::of(data.substr(0, 60)));
  h.update(bytes(data) + 60, 69);
  CHECK_EQ(h.hex(), std::string(kBoundaries[12].digest));
  CHECK_EQ(h.hex(), std::string(kBoundaries[12].digest));
}

TEST(sha256_empty_updates_are_no_ops) {
  const std::string data = pattern(64);
  Sha256 h;
  h.update(nullptr, 0);
  h.update(bytes(data), 0);
  h.update(std::string());
  h.update(bytes(data), 32);
  h.update(nullptr, 0);
  h.update(bytes(data) + 32, 32);
  CHECK_EQ(h.hex(), std::string(kBoundaries[6].digest));
}
