# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

package production_stats

import rego.v1

import data.utils

# input: {
#     "scope": <"list"|"view"> or null,
#     "auth": {
#         "user": {
#             "id": <num>,
#             "privilege": <"admin"|"user"|"worker"> or null
#         },
#         "organization": {
#             "id": <num>,
#             "owner": {
#                 "id": <num>
#             },
#             "user": {
#                 "role": <"owner"|"maintainer"|"supervisor"|"worker"> or null
#             }
#         } or null,
#     }
# }

default allow := false

# Production stats expose every worker's per-person output, so they stay
# admin-only. Note that utils.get_priority() has no entry for the "reviewer"
# group, so utils.has_perm() cannot be used to widen this without editing an
# upstream file.
allow if {
    utils.is_admin
}
