# Design：{{change-name}}

> 版本：v1.0 | 日期：{{date}}

## Layer 3 — 資料模型

### Entity：{{EntityName}}

| 欄位 | 型別 | 約束 | 說明 |
|------|------|------|------|
| `{{field}}` | string | NOT NULL | {{說明}} |
| `{{field}}` | string \| null | optional | {{說明}} |

**索引**：以 `({{key_fields}})` 唯一

**完整 JSON 範例**：

```json
{
  "{{field}}": "{{example-value}}",
  "{{field}}": null
}
```

---

## Layer 3 — API Schema（內部介面）

### {{InterfaceName}} 抽象介面

```python
from abc import ABC, abstractmethod

class {{InterfaceName}}(ABC):
    @abstractmethod
    def {{method}}(self, {{params}}) -> {{return_type}}: ...
```

### {{ConcreteClass}} 實作

```python
class {{ConcreteClass}}({{InterfaceName}}):
    def {{method}}(self, {{params}}) -> {{return_type}}:
        # {{實作說明}}
        ...
```

---

## 序列圖（選用）

```text
{{Actor}} -> {{Component}}: {{action}}
{{Component}} -> {{Storage}}: {{read/write}}
{{Storage}} --> {{Component}}: {{result}}
{{Component}} --> {{Actor}}: {{response}}
```
