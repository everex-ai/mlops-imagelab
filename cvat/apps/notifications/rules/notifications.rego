# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

package notifications

import rego.v1

# input: {
#     "scope": <"list"|"update"|"update:all"> or null,
#     "auth": {
#         "user": {
#             "id": <num>,
#             "privilege": <"admin"|"user"|"reviewer"|"worker"> or null
#         },
#         "organization": {...} or null,
#     },
#     "resource": {
#         "id": <num>,
#         "recipient": { "id": <num> }
#     } or null
# }

default allow := false

# Ownership, not role priority: utils.get_priority() has no entry for the fork's
# "reviewer" group, so utils.has_perm(utils.WORKER) would deny reviewers, who are
# half of this feature's audience. The views scope every query to the requesting
# user, independent of the organization context.
allow if {
    input.scope in {"list", "update:all"}
    input.auth.user.id != null
}

allow if {
    input.scope == "update"
    input.resource.recipient.id == input.auth.user.id
}
