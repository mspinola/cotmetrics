import time

import cotmetrics.utils as utils
from cotmetrics.CotDatabase import CotDatabase

# Instantiate once here
start_time = time.time()
cotDatabase = CotDatabase()
utils.get_cot_logger().debug(f"CotDatabase took: {time.time() - start_time:.2f}s")
