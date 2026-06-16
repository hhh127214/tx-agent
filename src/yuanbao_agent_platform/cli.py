from __future__ import annotations

import json

from yuanbao_agent_platform.platform import YuanbaoTestingPlatform


def main() -> None:
    platform = YuanbaoTestingPlatform()
    result = platform.run_demo()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
