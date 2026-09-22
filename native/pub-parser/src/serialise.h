// Serialisation of the intermediate model into the output bundle.
#ifndef PUBIR_SERIALISE_H
#define PUBIR_SERIALISE_H

#include <string>

#include "json.h"
#include "limits.h"
#include "model.h"

namespace pubir {

Json documentJson(const Document &doc);
Json assetsJson(const Document &doc);
// `status` is "ok", "truncated" or "failed". `failureCode`/`failureMessage`
// describe a parse that never produced a model.
Json reportJson(const Document &doc, const Limits &limits, const std::string &status,
                const std::string &failureCode = std::string(),
                const std::string &failureMessage = std::string());

} // namespace pubir

#endif
