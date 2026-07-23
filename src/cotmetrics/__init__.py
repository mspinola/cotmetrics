"""cotmetrics — turn raw COT data into positioning metrics and signals.

Re-exports the flat metric namespace (indicators/conditions/signals) so
``cotmetrics.calculate_cot_index`` etc. resolve directly. Deliberately does NOT
import the indexer/database singletons, so ``import cotmetrics`` stays cheap and
side-effect-free. For those, use ``from cotmetrics.indexer import get_indexer`` and
call it where the data is needed. The legacy ``cotIndexer`` name still resolves, but
it constructs at the import statement, which is the cost this layout avoids.
"""
from .conditions import *  # noqa: F401,F403
from .indicators import *  # noqa: F401,F403
from .signals import *  # noqa: F401,F403
