# CrashLoop / restart storm
# Keywords: restart crash oom
#
# Steps:
# 1. kubectl describe pod / check lastState.terminated.reason
# 2. Check memory limits vs usage
# 3. Rolling restart only after confirming config/image is healthy
