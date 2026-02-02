# 接入指南

## 接入指南

- [Python 示例](https://github.com/Deepcoin-exchange/openapi_python_example)
- [Golang 示例](https://github.com/Deepcoin-exchange/openapi_golang_example)
- [Telegram API交流群](https://t.me/Deepcoin_ApiOfficial)

## 请求验证

**API URL** `https://api.deepcoin.com`

### 生成 APIKey

在对任何请求进行签名之前，您必须通过交易网站创建一个 APIKey。创建 APIKey 后，您将获得 3 个必须记住的信息：

- APIKey
- SecretKey
- Passphrase

APIKey 和 SecretKey 将由平台随机生成和提供，Passphrase 将由您提供以确保 API 访问的安全性。平台将存储 Passphrase 加密后的哈希值进行验证，但如果您忘记 Passphrase，则无法恢复，请您通过交易网站重新生成新的 APIKey。

**每个 APIKey 最多可绑定 20 个 IP 地址；未绑定 IP 且拥有交易或提币权限的 APIKey，将在闲置 30 天之后自动删除。**

### 发起请求

所有 REST 私有请求头都必须包含以下内容：

- `DC-ACCESS-KEY` 字符串类型的 APIKey。
- `DC-ACCESS-SIGN` 使用 HMAC SHA256 哈希函数获得哈希值，再使用 Base-64 编码（请参阅签名）。
- `DC-ACCESS-TIMESTAMP` 发起请求的时间（UTC），如：2020-12-08T09:08:57.715Z
- `DC-ACCESS-PASSPHRASE` 您在创建 API 密钥时指定的 Passphrase。

所有请求都将被格式化为 application/json 类型的请求，并且具有有效的 JSON。

### 签名

`DC-ACCESS-SIGN` 的请求头是由 `timestamp + method + requestPath + body` 字符串（+表示字符串拼接），以及 `SecretKey`，使用 `HMAC SHA256`方法加密，通过 `Base-64`编码输出而得到的。

如：

```js
sign = CryptoJS.enc.Base64.stringify(
  CryptoJS.HmacSHA256(timestamp + 'GET' + '/users/self/verify', SecretKey)
)
```



其中，`timestamp` 的值为 `DC-ACCESS-TIMESTAMP` 请求头相同，为 ISO 格式，如 `2020-12-08T09:08:57.715Z`。

method 是请求方法，字母全部大写：`GET` 或 `POST`。 requestPath 是请求接口路径，例如：`/deepcoin/account/balance`。 body 是指请求主体的字符串，如果请求没有主体（通常为 GET 请求）则 body 可省略。如：

```json
{ "instId": "BTC-USDT", "lever": "5", "mgnMode": "isolated" }
```



> GET 请求参数是算作 requestPath，不算 body

SecretKey 为用户申请 APIKey 时所生成。如：`22582BD0CFF14C41EDBF1AB98506286D`

# 错误码

## 错误码

| 错误提示                             | HTTP 状态码 | 错误码 |
| ------------------------------------ | ----------- | ------ |
| Api 已被冻结，请联系客服处理         | 400         | 50100  |
| APIKey 与当前环境不匹配              | 401         | 50101  |
| 请求时间戳过期                       | 401         | 50102  |
| 请求头"DC-ACCESS-KEY"不能为空        | 401         | 50103  |
| 请求头"DC-ACCESS-PASSPHRASE"不能为空 | 401         | 50104  |
| 请求头"DC-ACCESS-PASSPHRASE"错误     | 401         | 50105  |
| 请求头"DC-ACCESS-SIGN"不能为空       | 401         | 50106  |
| 请求头"DC-ACCESS-TIMESTAMP"不能为空  | 401         | 50107  |
| 券商 ID 不存在                       | 401         | 50108  |
| 券商域名不存在                       | 401         | 50109  |
| 无效的 IP                            | 401         | 50110  |
| 无效的 DC-ACCESS-KEY                 | 401         | 50113  |
| 无效的 DC-ACCESS-TIMESTAMP           | 401         | 50112  |
| 无效的签名                           | 401         | 50111  |
| 无效的授权                           | 401         | 50114  |
| 无效的请求类型                       | 405         | 50115  |

# 获取资金账户余额

## 获取资金账户余额

获取资金账户所有资产列表，查询各币种的余额，冻结和可用等信息

限频：每秒 1 次

## 请求地址

```
GET /deepcoin/account/balances
```

## 请求参数

| 字段名   | 是否必填 | 类型   | 字段描述                           |
| -------- | -------- | ------ | ---------------------------------- |
| instType | 是       | string | 产品类型 现货: `SPOT` 合约: `SWAP` |
| ccy      | 否       | string | 币种, 例:`USDT` 不传则查询所有资产 |

## 响应参数

| 字段名    | 类型   | 字段描述     |
| --------- | ------ | ------------ |
| ccy       | string | 币种         |
| bal       | string | 余额         |
| frozenBal | string | 冻结(不可用) |
| availBal  | string | 可用余额     |

## 响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": [
        {
            "ccy": "USDT",
            "bal": "41473433.53",
            "frozenBal": "192.05",
            "availBal": "41473234.12"
        },
        {
            "ccy": "BTC",
            "bal": "0.99715276",
            "frozenBal": "0.00135139",
            "availBal": "0.99448105"
        }
    ]
}
```

# 获取资金流水

## 获取资金流水

查询资金账户的资金流水

限频：每秒 1 次

### 请求地址

```
GET /deepcoin/account/bills
```

### 请求参数

| 字段名   | 是否必填 | 类型    | 描述                                                         |
| -------- | -------- | ------- | ------------------------------------------------------------ |
| instType | 是       | string  | 产品类型 现货: `SPOT` 合约: `SWAP`                           |
| ccy      | 否       | string  | 币种                                                         |
| type     | 否       | string  | 账户类型 资金收入: `2` 资金支出: `3` 资金转入: `4` 手续费: `5` |
| after    | 否       | integer | 查询在此之前的内容，时间为毫秒格式时间戳                     |
| before   | 否       | integer | 查询在此之前的内容，时间为毫秒格式时间戳                     |
| limit    | 否       | integer | 分页返回的结果数最大为 `100` 不填默认返回 `100` 条           |

### 响应参数

| 字段名   | 类型   | 描述                                                         |
| -------- | ------ | ------------------------------------------------------------ |
| billId   | string | 账单 ID                                                      |
| ccy      | string | 账户余额币种                                                 |
| clientId | string | 客户自定义 ID                                                |
| balChg   | string | 账户层面的余额变动数量                                       |
| bal      | string | 账户层面的余额数量                                           |
| type     | string | 账单类型 `1`: "盈亏", `2`: "资金收支", `3`: "系统转入", `4`: "转出", `5`: "手续费", `7`: "资金费用", `8`: "结算", `a`: "强平", `g`: "预扣分润", `h`: "预扣分润退还", `i`: "带单分润", `j`: "体验金发放", `k`: "体验金回收" |
| ts       | string | 账单创建时间 Unix 时间戳的格式                               |

### 响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": [
        {
            "billId": "1000749090787153",
            "ccy": "USDT",
            "clientId": "",
            "balChg": "-0.08911552",
            "bal": "210523.96755368",
            "type": "5",
            "ts": "1736760623000"
        },
        {
            "billId": "1000749090787141",
            "ccy": "USDT",
            "clientId": "",
            "balChg": "-0.11841053",
            "bal": "210527.00491822",
            "type": "5",
            "ts": "1736760503000"
        }
    ]
}
```

# 获取持仓列表

## 获取持仓列表

获取持仓列表

限频：每秒 1 次

### 请求地址

```
GET /deepcoin/account/positions
```

### 请求参数

| 字段名   | 是否必填 | 类型   | 字段描述                           |
| -------- | -------- | ------ | ---------------------------------- |
| instType | 是       | string | 产品类型 合约: `SWAP` 现货: `SPOT` |
| instId   | 否       | string | 产品 ID                            |

### 响应参数

| 字段名           | 类型   | 字段描述                                               |
| ---------------- | ------ | ------------------------------------------------------ |
| instType         | string | 产品类型 现货展示为：`SPOT`                            |
| mgnMode          | string | 保障模式: cross=全仓 现货展示为: `cash`                |
| instId           | string | 产品 ID                                                |
| posId            | string | 订单 ID                                                |
| posSide          | string | 持仓方向 多: `long`  空: `short`  现货展示空           |
| pos              | string | 持仓数量 单位:` 张`                                    |
| avgPx            | string | 开仓均价  现货展示为：买入均价                         |
| lever            | string | 杠杆大小  现货展示空                                   |
| liqPx            | string | 强平价  现货展示空                                     |
| useMargin        | string | 占用保证金  现货展示空                                 |
| unrealizedProfit | string | 未实现盈亏                                             |
| mrgPosition      | string | 合约仓位类型 合仓: `merge` 分仓: `split`  现货展示为空 |
| ccy              | string | 占用保证金币种                                         |
| uTime            | string | 持仓创建时间，Unix 时间戳格式的毫秒数格式              |
| cTime            | string | 最近一次持仓更新时间，Unix 时间戳格式的毫秒数格式      |

### 响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": [
        {
            "instType": "SWAP",
            "mgnMode": "cross",
            "instId": "BTC-USDT-SWAP",
            "posId": "1000587858872759",
            "posSide": "long",
            "pos": "200",
            "avgPx": "97603",
            "lever": "1",
            "liqPx": "0.1",
            "useMargin": "19520.6",
            "unrealizedProfit": "100.5",
            "mrgPosition": "split",
            "ccy": "USDT",
            "uTime": "1739243187000",
            "cTime": "1739243187000"
        }
    ]
}
```

# 设置杠杆倍数

## 设置杠杆倍数

设置杠杆

限频：每秒 1 次

### 请求地址

```
POST /deepcoin/account/set-leverage
```

### 请求参数

| 字段名      | 是否必填 | 类型   | 字段描述                                  |
| ----------- | -------- | ------ | ----------------------------------------- |
| instId      | 是       | string | 产品 ID                                   |
| lever       | 是       | string | 杠杆倍数 最小值: `1`                      |
| mgnMode     | 是       | string | 保证金模式 全仓: `cross` 逐仓: `isolated` |
| mrgPosition | 是       | string | 合并仓位 合仓: `merge` 分仓: `split`      |

### 请求示例

```text
{
    "instId": "BTC-USDT-SWAP",
    "lever": "17",
    "mgnMode": "cross",
    "mrgPosition": "merge"
}
```



### 响应参数

| 字段名      | 类型   | 字段描述                        |
| ----------- | ------ | ------------------------------- |
| instId      | string | 产品 ID                         |
| lever       | string | 杠杆倍数                        |
| mgnMode     | string | 保证金模式 cross:全仓           |
| mrgPosition | string | 合并仓位 merge:合仓; split:分仓 |
| sCode       | string | 事件执行结果的状态码 0:成功;    |
| sMsg        | string | 事件执行失败的消息              |

### 响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": {
        "instId": "BTC-USDT-SWAP",
        "lever": "17",
        "mgnMode": "cross",
        "mrgPosition": "merge",
        "sCode": "0",
        "sMsg": ""
    }
}
```

# 获取产品深度列表

## 获取产品深度列表

获取产品深度列表

限速规则: IP

限频: 每秒 5 次

### 请求地址

```
GET /deepcoin/market/books
```

### 请求参数

| 字段名 | 否必填 | 类型    | 字段描述                       |
| ------ | ------ | ------- | ------------------------------ |
| instId | 是     | string  | 产品 ID                        |
| sz     | 是     | integer | 深度档位数量，最大值可传 `400` |

### 响应参数

| 字段名 | 类型  | 字段描述                                        |
| ------ | ----- | ----------------------------------------------- |
| bids   | array | 当前的所有买单集合 格式:[[价格 1, 数量 1], ...] |
| asks   | array | 当前的所有卖单集合 格式:[[价格 1, 数量 1], ...] |

### 返回示例

```json
{
    "code": "0",
    "msg": "",
    "data": {
        "bids": [
            [
                "97515.7",
                "14.507"
            ]
        ],
        "asks": [
            [
                "97516",
                "9.303"
            ]
        ]
    }
}
```

# 获取交易产品K线数据

## 获取交易产品 K 线数据

获取交易产品 K 线数据 返回值数组顺序分别为是:[数据生成的时间,开盘价格,最高价格,最低价格,收盘价格,交易量(数值为交易货币的数量),交易量(数值为计价货币的数量)]

限速规则: IP

限频: 每秒 5 次

### 请求地址

```
GET /deepcoin/market/candles
```

### 请求参数

| 字段名 | 是否必填 | 类型    | 字段描述                                                     |
| ------ | -------- | ------- | ------------------------------------------------------------ |
| instId | 是       | string  | 产品 ID                                                      |
| bar    | 否       | string  | 时间粒度 默认值: `1m` 1分钟: `1m` 5分钟: `5m` 15分钟: `15m` 30分钟: `30m` 1小时: `1H` 4小时: `4H` 12小时: `12H` 一天: `1D` 一周: `1W` 一月: `1M` 一年: `1Y` |
| after  | 否       | integer | 请求此时间戳之前(更旧的数据)的分页内容 传的值为对应接口的 ts |
| limit  | 否       | integer | 分页返回的结果集数量最大为 `300` 不填默认返回 `100` 条       |

### 返回示例

```text
{
    "code": "0",
    "msg": "",
    "data": [
        [
            "1739157660000",  // 时间戳
            "95900.5",	      // 开盘价
            "95932.2",	      // 最高价
            "95850.4",	      // 最低价
            "95913.4",        // 收盘价
            "20084",          // 数量
            "1925967.4841"    // 成交金额
        ],
        [
            "1739157600000",
            "95963.3",
            "95983.2",
            "95898.2",
            "95900.5",
            "5472",
            "524979.2415"
        ]
    ]
}
```

# 获取交易产品基础信息

## 获取交易产品基础信息

获取所有可交易产品的信息列表

限速规则：IP

限频：每秒 5 次

### 请求地址

```
GET /deepcoin/market/instruments
```

### 请求参数

| 字段名   | 否必填 | 类型   | 字段描述                           |
| -------- | ------ | ------ | ---------------------------------- |
| instType | 是     | string | 产品类型 现货: `SPOT` 合约: `SWAP` |
| uly      | 否     | string | 标的指数,仅适用于永续              |
| instId   | 否     | string | 产品 ID                            |

### 响应参数

| 字段名   | 类型   | 字段描述                                                     |
| -------- | ------ | ------------------------------------------------------------ |
| instType | string | 产品类型                                                     |
| instId   | string | 产品 ID                                                      |
| uly      | string | 标的指数 仅适用于永续                                        |
| baseCcy  | string | 交易货币币种 仅适用于币币                                    |
| quoteCcy | string | 计价货币币种 仅适用于币币                                    |
| ctVal    | string | 合约面值 仅适用于永续                                        |
| ctValCcy | string | 合约面值计价币种 仅适用于永续                                |
| listTime | string | 上线日期 Unix 时间戳的毫秒数格式                             |
| lever    | string | 该 instId 支持的最大杠杆倍数 不适用于币币/期权               |
| tickSz   | string | 下单价格精度                                                 |
| lotSz    | string | 下单数量精度                                                 |
| minSz    | string | 最小下单数量                                                 |
| ctType   | string | 合约类型 linear:正向合约;inverse:反向合约; 仅适用于永续      |
| alias    | string | 合约日期别名 this_week:本周;next_week:次周;quarter:季度;next_quarter:次季度; 仅适用于交割 |
| state    | string | 产品状态 live:交易中;suspend:暂停中;preopen:预上线;settlement:资金费结算; |
| maxLmtSz | string | 合约或现货限价单的单笔最大委托数量                           |
| maxMktSz | string | 合约或现货市价单的单笔最大委托数量                           |

### 返回示例

```json
{
    "code": "0",
    "msg": "",
    "data": [
        {
            "instType": "SWAP",
            "instId": "BTC-USDT-SWAP",
            "uly": "",
            "baseCcy": "BTC",
            "quoteCcy": "USDT",
            "ctVal": "0.001",
            "ctValCcy": "",
            "listTime": "0",
            "lever": "125",
            "tickSz": "0.1",
            "lotSz": "1",
            "minSz": "1",
            "ctType": "",
            "alias": "",
            "state": "live",
            "maxLmtSz": "200000",
            "maxMktSz": "200000"
        }
    ]
}
```

# 获取所有产品行情信息

## 获取所有产品行情信息

获取产品行情信息

限速规则: IP

限频: 每秒 5 次

### 请求地址

```
GET /deepcoin/market/tickers
```

### 请求参数

| 字段名   | 是否必填 | 类型   | 字段描述                           |
| -------- | -------- | ------ | ---------------------------------- |
| instType | 是       | string | 产品类型 现货: `SPOT` 合约: `SWAP` |
| uly      | 否       | string | 标的指数, 仅适用于永续             |

### 响应参数

| 字段名    | 类型   | 字段描述                                    |
| --------- | ------ | ------------------------------------------- |
| instType  | string | 产品类型                                    |
| instId    | string | 产品 ID                                     |
| last      | string | 最新成交价                                  |
| lastSz    | string | 最新成交的数量                              |
| askPx     | string | 卖一价                                      |
| askSz     | string | 卖一价的挂单数量                            |
| bidPx     | string | 买一价                                      |
| bidSz     | string | 买一价的挂单数量                            |
| open24h   | string | 24 小时开盘价                               |
| high24h   | string | 24 小时最高价                               |
| low24h    | string | 24 小时最低价                               |
| volCcy24h | string | 24 小时成交量 数值为计价货币的数量          |
| vol24h    | string | 24 小时成交量 数值为交易货币的数量          |
| sodUtc0   | string | UTC 0 时开盘价                              |
| sodUtc8   | string | UTC+8 时开盘价                              |
| ts        | string | ticker 数据产生时间 Unix 时间戳的毫秒数格式 |

### 返回示例

```json
{
    "code": "0",
    "msg": "",
    "data": [
        {
            "instType": "SWAP",
            "instId": "BTC-USD-SWAP",
            "last": "96127.5",
            "lastSz": "",
            "askPx": "96127.8",
            "askSz": "179208",
            "bidPx": "96127.3",
            "bidSz": "2951",
            "open24h": "95596.6",
            "high24h": "96531.5",
            "low24h": "95247",
            "volCcy24h": "55.814169",
            "vol24h": "5350671",
            "sodUtc0": "",
            "sodUtc8": "",
            "ts": "1739242026000"
        }
    ]
}
```

# 获取交易产品指数K线数据

## 获取交易产品指数 K 线数据

获取交易产品指数 K 线数据 返回值数组顺序分别为是:[数据生成的时间,开盘价格,最高价格,最低价格,收盘价格,交易量(0),交易量(0)]

限速规则: IP

限频: 每秒 5 次

### 请求地址

```
GET /deepcoin/market/index-candles
```

### 请求参数

| 字段名 | 是否必填 | 类型    | 字段描述                                                     |
| ------ | -------- | ------- | ------------------------------------------------------------ |
| instId | 是       | string  | 产品 ID                                                      |
| bar    | 否       | string  | 时间粒度 默认值: `1m` 1分钟: `1m` 5分钟: `5m` 15分钟: `15m` 30分钟: `30m` 1小时: `1H` 4小时: `4H` 12小时: `12H` 一天: `1D` 一周: `1W` 一月: `1M` 一年: `1Y` |
| after  | 否       | integer | 请求此时间戳之前(更旧的数据)的分页内容 传的值为对应接口的 ts |
| limit  | 否       | integer | 分页返回的结果集数量最大为 `300` 不填默认返回 `100` 条       |

### 返回示例

```text
{
    "code": "0",
    "msg": "",
    "data": [
        [
            "1739157660000",  // 时间戳
            "95900.5",	      // 开盘价
            "95932.2",	      // 最高价
            "95850.4",	      // 最低价
            "95913.4",        // 收盘价
            "0",          // 数量
            "0"    // 成交金额
        ],
        [
            "1739157600000",
            "95963.3",
            "95983.2",
            "95898.2",
            "95900.5",
            "0",
            "0"
        ]
    ]
}
```

# 获取成交记录

获取产品成交记录

**限速：** 1次/1s

**限速规则：** IP

## 请求地址

```text
GET /deepcoin/market/trades
```



## 请求参数

| 参数名       | 类型    | 是否必须 | 描述                                             | 示例     |
| ------------ | ------- | -------- | ------------------------------------------------ | -------- |
| instId       | String  | 是       | 产品ID                                           | BTC-USDT |
| productGroup | String  | 是       | 产品组 `Spot:现货` `Swap:币本位` `SwapU:u本位`   | Spot     |
| limit        | integer | 否       | 分页返回的结果集数量,最大为500,不填默认返回100条 | 100      |

## 响应参数

| 参数名  | 类型   | 描述                                                         | 示例          |
| ------- | ------ | ------------------------------------------------------------ | ------------- |
| instId  | String | 产品ID                                                       | BTC-USDT      |
| tradeId | String | 成交ID                                                       | T1234567890   |
| px      | String | 成交价格                                                     | 38715.7       |
| sz      | String | 成交数量 `对于币币交易,成交数量的单位为交易货币;`对于交割、永续以及期权,单位为张 | 0.1           |
| side    | String | 吃单方向 `buy:买`sell:卖                                     | buy           |
| ts      | String | 成交时间,Unix时间戳的毫秒数格式                              | 1597026383085 |

## 响应示例

```json
{
  "code": 0,
  "msg": "success",
  "data": [
    {
      "instId": "BTC-USDT",
      "tradeId": "T1234567890",
      "px": "38715.7",
      "sz": "0.1",
      "side": "buy",
      "ts": "1597026383085"
    },
    {
      "instId": "BTC-USDT",
      "tradeId": "T1234567891",
      "px": "38710.2",
      "sz": "0.5",
      "side": "sell",
      "ts": "1597026383086"
    }
  ]
}
```

# 获取交易产品标记价K线数据

## 获取交易产品标记价 K 线数据

获取交易产品标记价 K 线数据 返回值数组顺序分别为是:[数据生成的时间,开盘价格,最高价格,最低价格,收盘价格,交易量(0),交易量(0)]

限速规则: IP

限频: 每秒 5 次

### 请求地址

```
GET /deepcoin/market/mark-price-candles
```

### 请求参数

| 字段名 | 是否必填 | 类型    | 字段描述                                                     |
| ------ | -------- | ------- | ------------------------------------------------------------ |
| instId | 是       | string  | 产品 ID                                                      |
| bar    | 否       | string  | 时间粒度 默认值: `1m` 1分钟: `1m` 5分钟: `5m` 15分钟: `15m` 30分钟: `30m` 1小时: `1H` 4小时: `4H` 12小时: `12H` 一天: `1D` 一周: `1W` 一月: `1M` 一年: `1Y` |
| after  | 否       | integer | 请求此时间戳之前(更旧的数据)的分页内容 传的值为对应接口的 ts |
| limit  | 否       | integer | 分页返回的结果集数量最大为 `300` 不填默认返回 `100` 条       |

### 返回示例

```text
{
    "code": "0",
    "msg": "",
    "data": [
        [
            "1739157660000",  // 时间戳
            "95900.5",	      // 开盘价
            "95932.2",	      // 最高价
            "95850.4",	      // 最低价
            "95913.4",        // 收盘价
            "0",          // 数量
            "0"    // 成交金额
        ],
        [
            "1739157600000",
            "95963.3",
            "95983.2",
            "95898.2",
            "95900.5",
            "0",
            "0"
        ]
    ]
}
```

# 获取交易产品阶梯保证金信息

## 获取交易产品阶梯保证金信息

获取交易产品阶梯保证金信息

限速规则: IP

限频: 每秒 1 次

### 请求地址

```
GET /deepcoin/market/step-margin
```

### 请求参数

| 字段名 | 是否必填 | 类型   | 字段描述           |
| ------ | -------- | ------ | ------------------ |
| instId | 是       | string | 产品 ID,仅支持SWAP |

### 响应参数

| 字段名                | 类型    | 字段描述 |
| --------------------- | ------- | -------- |
| grade                 | int     | 等级     |
| leverage              | string  | 杠杆     |
| maxContractValue      | float64 | 最大可开 |
| maintenanceMarginRate | string  | 维保率   |

### 返回示例

```text
{
    "code": "0",
    "msg": "",
    "data": [
        {
            "grade": 1,
            "leverage": "125",
            "maxContractValue": 12000,
            "maintenanceMarginRate": "0.004"
        },
        {
            "grade": 2,
            "leverage": "76.923077",
            "maxContractValue": 18000,
            "maintenanceMarginRate": "0.0065"
        },
        {
            "grade": 3,
            "leverage": "55.555556",
            "maxContractValue": 24000,
            "maintenanceMarginRate": "0.009"
        }
    ]
}
```

# 获取产品深度点差信息

## 获取产品深度点差信息

获取产品深度点差信息

限速规则: IP

限频: 每秒 1 次

### 请求地址

```
GET /deepcoin/market/book-spread
```

### 请求参数

| 字段名 | 否必填 | 类型   | 字段描述                                |
| ------ | ------ | ------ | --------------------------------------- |
| instId | 是     | string | 产品 ID                                 |
| value  | 是     | float  | 具体币数量或者USDT                      |
| vType  | 否     | string | 具体价值单位.0:USDT,1:BCT,ETH... 默认 0 |

### 响应参数

| 字段名         | 类型   | 字段描述     |
| -------------- | ------ | ------------ |
| instId         | string | 产品 ID      |
| askSpreadValue | string | 卖盘深度点差 |
| bidSpreadValue | string | 买盘深度点差 |

### 返回示例

```json
{
  "code": "0",
  "msg": "",
  "data": {
    "instId": "BTC-USDT-SWAP",
    "askSpreadValue": "0.000550",
    "bidSpreadValue": "0.000661"
  }
}
```

# 获取系统信息

## 获取系统信息

获取系统信息

限速规则: IP

限频: 每秒 1 次

### 请求系统时间

```
GET /deepcoin/market/time
```

### 请求参数

无

### 响应参数

| 字段名 | 类型  | 字段描述                  |
| ------ | ----- | ------------------------- |
| ts     | int64 | 当前系统时间戳(单位:毫秒) |

### 返回示例

```json
{
  "code": "0",
  "msg": "",
  "data": {
    "ts": 1762414261346
  }
}
```



### 系统联通性

```
GET /deepcoin/market/ping
```

### 请求参数

无

### 响应参数

无

### 返回示例

```json
{
  "code": "0",
  "msg": "",
  "data": {}
}
```

# 下单

## 下单

只有当您的账户有足够的资金才能下单

限频：每秒 1 次

### 请求地址

```
POST /deepcoin/trade/order
```

### 请求参数

| 字段名       | 是否必填 | 类型    | 字段描述                                                     |
| ------------ | -------- | ------- | ------------------------------------------------------------ |
| instId       | 是       | string  | 产品 ID                                                      |
| tdMode       | 是       | string  | 交易模式 逐仓: `isolated` 全仓: `cross`                      |
| ccy          | 否       | string  | 保证金币种，仅适用于单币种保证金模式下的全仓杠杆订单         |
| clOrdId      | 否       | string  | 客户自定义订单 ID 字母(区分大小写) 与数字的组合 可以是纯字母 纯数字且长度要在 `1-32` 位之间 暂不支持该参数传参 |
| tag          | 否       | string  | 订单标签 字母(区分大小写) 与数字的组合 可以是纯字母 纯数字 且长度在 `1-16` 位之间 暂不支持该参数传参 |
| side         | 是       | string  | 订单方向 买: `buy` 卖: `sell`                                |
| posSide      | 否       | string  | 持仓方向 产品类型为 `SWAP` 时必填 多: `long` 空: `short`     |
| mrgPositio n | 否       | string  | 合并合仓 产品类型为 SWAP 时必填 合仓: `merge` 分仓: `split`  |
| closePosId   | 否       | string  | 等待平仓的仓位 ID 分仓模式必填                               |
| ordType      | 是       | string  | 订单类型 市价单: `market` 限价单: `limit` 只做 maker 单: `post_only` 立即成交或撤销单: `ioc` |
| sz           | 是       | string  | 委托数量,通过 `获取交易产品基础信息` 接口获取 最小下单数量(minSz) |
| px           | 否       | string  | 委托价格,通过 `获取交易产品基础信息` 接口获取 下单价格精度(tickSz) 仅适用于 `limit,post_only` 类型的订单 |
| reduceOnly   | 否       | boolean | 是否只减仓,`true` 或 `false` 默认 false 仅适用于币币杠杆 以及买卖模式下的交割/永续 仅适用于单币种保证金模式和跨币种保证金模式 |
| tgtCcy       | 否       | string  | 市价单委托数量的类型，仅适用于币币订单 交易货币: `base_ccy` 计价货币: `quote_ccy` |
| tpTriggerPx  | 否       | string  | 止盈触发价 仅适用于止盈止损单                                |
| slTriggerPx  | 否       | string  | 止损触发价 仅适用于止盈止损单                                |

### 请求示例

```json
{
  "instId": "BTC-USDT",
  "tdMode": "cash",
  "ccy": "USDT",
  "clOrdId": "string",
  "tag": "string",
  "side": "buy",
  "posSide": "long",
  "mrgPosition": "merge",
  "closePosId": "1001063717138767",
  "ordType": "limit",
  "sz": "0.0004",
  "px": "0.01",
  "reduceOnly": "boolean",
  "tgtCcy": "string",
  "tpTriggerPx": "10000.1",
  "slTriggerPx": "9000.1"
}



// 市价做多，买入开多
{
    "instId": "BTC-USDT-SWAP",
    "tdMode": "cross",
    "side": "buy",
    "ordType": "market",
    "sz": "5",
    "posSide": "long",
    "mrgPosition": "merge",
}

// 市价卖出平多
{
    "instId": "BTC-USDT-SWAP",
    "tdMode": "cross",
    "side": "sell",
    "ordType": "market",
    "sz": "5",
    "posSide": "long",
    "mrgPosition": "merge",
}

// 市价做空,卖出开空
{
    "instId": "BTC-USDT-SWAP",
    "tdMode": "cross",
    "side": "sell",
    "ordType": "market",
    "sz": "1",
    "posSide": "short",
    "mrgPosition": "merge",
}

// 市价买入平空
{
    "instId": "BTC-USDT-SWAP",
    "tdMode": "cross",
    "side": "buy",
    "ordType": "market",
    "sz": "1",
    "posSide": "short",
    "mrgPosition": "merge",
}

// 限价买入开多
{
    "instId": "BTC-USDT-SWAP",
    "tdMode": "cross",
    "side": "buy",
    "ordType": "limit",
    "sz": "1",
    "px": "23000",
    "posSide": "long",
    "mrgPosition": "merge",
}

// 限价卖出做空
{
    "instId": "BTC-USDT-SWAP",
    "tdMode": "cross",
    "side": "sell",
    "ordType": "limit",
    "sz": "1",
    "px": "35000",
    "posSide": "short",
    "mrgPosition": "merge",
}
```



### 响应参数

| 字段名  | 类型   | 字段描述                     |
| ------- | ------ | ---------------------------- |
| ordId   | string | 订单 ID                      |
| clOrdId | string | 客户自定义订单 ID            |
| tag     | string | 订单标签                     |
| sCode   | string | 事件执行结果的状态码 0:成功; |
| sMsg    | string | 事件执行失败时的消息         |

### 响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": {
        "ordId": "1000587866646229",
        "clOrdId": "",
        "tag": "",
        "sCode": "0",
        "sMsg": ""
    }
}
```

# 改单

## 改单

对指定委托进行价格、数量进行修改

限频：每秒 1 次

### 请求地址

```
POST /deepcoin/trade/replace-order
```

### 请求参数

| 字段名     | 是否必填 | 类型    | 字段描述         |
| ---------- | -------- | ------- | ---------------- |
| OrderSysID | 是       | string  | 委托 ID          |
| price      | 否       | float   | 价格             |
| volume     | 否       | integer | 数量，单位：`张` |

### 请求示例

```text
{
  "OrderSysID": "'12345'",
  "price": 6000.5,
  "volume": 5
}
```



### 响应参数

| 字段名    | 类型    | 字段描述 |
| --------- | ------- | -------- |
| errorCode | integer | 错误码   |
| errorMsg  | string  | 错误文案 |
| ordId     | string  | 委托 ID  |

### 响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": {
        "errorCode": 0,
        "errorMsg": "",
        "ordId": "1000587867035933"
    }
}
```

# 撤单

## 撤单

撤销之前下的未完成订单

限频：每秒 1 次

### 请求地址

```
POST /deepcoin/trade/cancel-order
```

### 请求参数

| 字段名 | 是否必填 | 类型   | 字段描述 |
| ------ | -------- | ------ | -------- |
| instId | 是       | string | 产品 ID  |
| ordId  | 是       | string | 订单 ID  |

### 请求示例

```json
{
    "instId": "BTC-USDT-SWAP",
    "ordId": "1000587866272245"
}
```



### 响应参数

| 字段名  | 类型   | 字段描述                     |
| ------- | ------ | ---------------------------- |
| ordId   | string | 订单 ID                      |
| clOrdId | string | 客户自定义订单 ID            |
| sCode   | string | 事件执行结果的状态码 0:成功; |
| sMsg    | string | 事件执行失败时的消息         |

### 响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": {
        "ordId": "1000587866272245",
        "clOrdId": "",
        "sCode": "0",
        "sMsg": ""
    }
}
```

# 批量撤单

## 批量撤单

批量撤销限价委托，单次批量撤销最多 50 个限价委托

限频：每秒 1 次

### 请求地址

```
POST /deepcoin/trade/batch-cancel-order
```

### 请求参数

| 字段名      | 是否必填 | 类型     | 字段描述        |
| ----------- | -------- | -------- | --------------- |
| OrderSysIDs | 是       | string[] | 指定限价委托 ID |

### 请求示例

```json
{
    "orderSysIDs": [
        "1000587865918838",
        "1000587865914949"
    ]
}
```



### 响应参数

| 字段名      | 类型     | 字段描述     |
| ----------- | -------- | ------------ |
| errorList   | string[] | 撤单失败类型 |
| > memberId  | string   | 用户 id      |
| > accountId | string   | 账户 id      |
| >orderSysId | string   | 委托 id      |
| > errorCode | integer  | 错误码       |
| > errorMsg  | string   | 错误文案     |

### 响应示例

```json
// 无错误
{
    "code": "0",
    "msg": "",
    "data": {
        "errorList": [

        ]
    }
}

// 部分订单撤单失败
{
    "code": "0",
    "msg": "",
    "data": {
        "errorList": [
            {
                "memberId": "36006290",
                "accountId": "36006290",
                "orderSysId": "1000587865918838",
                "errorCode": 24,
                "errorMsg": "OrderNotFound:1000587865918838"
            },
            {
                "memberId": "36006290",
                "accountId": "36006290",
                "orderSysId": "1000587865914949",
                "errorCode": 24,
                "errorMsg": "OrderNotFound:1000587865914949"
            }
        ]
    }
}
```

# 撤销条件单

## 撤销条件单

撤销之前下的未触发条件单

限频：60次/2s

限速规则：

- 衍生品：UserID + (instrumentType, underlying)
- 币币：UserID + (instrumentType, instrumentID)

### 请求地址

```
POST /deepcoin/trade/cancel-trigger-order
```

### 请求参数

| 字段名  | 是否必填 | 类型   | 字段描述                           |
| ------- | -------- | ------ | ---------------------------------- |
| instId  | 是       | string | 产品ID                             |
| ordId   | 是       | string | 条件单订单ID                       |
| clOrdId | 否       | string | 客户自定义订单ID（暂不支持该参数） |

### 请求示例

```json
{
    "instId": "BTC-USDT-SWAP",
    "ordId": "1001063717138767"
}
```



### 响应参数

| 字段名  | 类型   | 字段描述                        |
| ------- | ------ | ------------------------------- |
| ordId   | string | 订单ID                          |
| clOrdId | string | 客户自定义订单ID                |
| sCode   | string | 事件执行结果的状态码，0代表成功 |
| sMsg    | string | 事件执行失败时的消息            |

### 响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": {
        "ordId": "1001063717138767",
        "clOrdId": "",
        "sCode": "0",
        "sMsg": ""
    }
}
```



### 错误响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": {
        "ordId": "",
        "clOrdId": "",
        "sCode": "1033201232",
        "sMsg": "Order not found"
    }
}
```



### 注意事项

- 只能撤销未触发的条件单
- 支持现货和衍生品条件单
- 订单必须属于已认证的用户
- 按用户和产品类型进行限速

[
  ](https://www.deepcoin.com/docs/zh/DeepCoinTrade/batchCancelOrder)

# 一键撤单

## 一键撤单

一键撤单撤销限价委托，最多每秒一次请求（只支持合约）

限频：每秒 1 次

### 请求地址

```
POST /deepcoin/trade/swap/cancel-all
```

### 请求参数

| 字段名        | 是否必填 | 类型    | 字段描述                                                    |
| ------------- | -------- | ------- | ----------------------------------------------------------- |
| InstrumentID  | 是       | string  | 指定交易对                                                  |
| ProductGroup  | 是       | string  | 交易对类型  合约（币本位： `Swap`） 合约（U本位： `SwapU`） |
| IsCrossMargin | 是       | integer | 交易对类型 全仓: `1` 逐仓: `0`                              |
| IsMergeMode   | 是       | integer | 交易对类型 合仓: `1` 分仓: `0`                              |

### 请求示例

```json
{
  "InstrumentID": "BTCUSDT",
  "ProductGroup": "SwapU",
  "IsCrossMargin": 1,
  "IsMergeMode": 0
}
```



### 响应参数

| 字段名       | 是否必填 | 字段描述     |
| ------------ | -------- | ------------ |
| errorList    | string[] | 撤单失败类型 |
| > memberId   | string   | 用户 id      |
| > accountId  | string   | 账户 id      |
| > orderSysId | string   | 委托 id      |
| > errorCode  | integer  | 错误码       |
| > errorMsg   | string   | 错误文案     |

### 响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": {
        "errorList": []
    }
}
```

# 成交明细

## 获取成交明细

获取成交明细

限频：每秒 1 次

### 请求地址

```
GET /deepcoin/trade/fills
```

### 请求参数

| 字段名   | 是否必填 | 类型    | 字段描述                                                     |
| -------- | -------- | ------- | ------------------------------------------------------------ |
| instType | 是       | string  | 产品类型 现货: `SPOT` 合约: `SWAP`                           |
| instId   | 否       | string  | 产品 ID                                                      |
| ordId    | 否       | string  | 订单 ID                                                      |
| after    | 否       | string  | 请求此 ID 之前(更旧的数据)的分页内容，传的值为对应接口的 billId |
| before   | 否       | string  | 请求此 ID 之后(更新的数据)的分页内容，传的值为对应接口的 billId |
| begin    | 否       | integer | 请求此时间戳之后的成交明细，Unix 时间戳格式，单位为毫秒      |
| end      | 否       | integer | 请求此时间戳之前的成交明细，Unix 时间戳格式，单位为毫秒      |
| limit    | 否       | integer | 分页返回的结果集数量，最大为 `100` 个，默认返回 `100` 条     |

### 响应参数

| 字段名   | 类型   | 字段描述                                 |
| -------- | ------ | ---------------------------------------- |
| instType | string | 产品类型                                 |
| instId   | string | 产品 ID                                  |
| tradeId  | string | 最新成交 ID                              |
| ordId    | string | 订单 ID                                  |
| clOrdId  | string | 用户自定义订单 ID                        |
| billId   | string | 账单 ID                                  |
| tag      | string | 订单标签                                 |
| fillPx   | string | 最新成交价格                             |
| fillSz   | string | 最新成交数量                             |
| side     | string | 订单方向 买: `buy` 卖: `sell`            |
| posSide  | string | 持仓方向 多: `long` 空: `short`          |
| execType | string | 流动性方向 taker: `T` maker: `M`         |
| feeCcy   | string | 交易手续费币种或者返佣金币种             |
| fee      | string | 交易手续费                               |
| ts       | string | 成交明细产生时间 Unix 时间戳的毫秒数格式 |

### 响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": [
        {
            "instType": "SWAP",
            "instId": "BTC-USDT-SWAP",
            "tradeId": "1000169956494218",
            "ordId": "1000587866072658",
            "clOrdId": "",
            "billId": "10001699564942181",
            "tag": "",
            "fillPx": "98230.5",
            "fillSz": "200",
            "side": "sell",
            "posSide": "short",
            "execType": "T",
            "feeCcy": "USDT",
            "fee": "5.89383",
            "ts": "1739261250000"
        },
        {
            "instType": "SWAP",
            "instId": "BTC-USDT-SWAP",
            "tradeId": "1000169956494217",
            "ordId": "1000587866072658",
            "clOrdId": "",
            "billId": "10001699564942171",
            "tag": "",
            "fillPx": "98230.5",
            "fillSz": "50",
            "side": "sell",
            "posSide": "short",
            "execType": "T",
            "feeCcy": "USDT",
            "fee": "1.4734575",
            "ts": "1739261250000"
        }
    ]
}
```

# 根据id获取指定委托信息

## 根据 id 获取指定委托信息

根据 id 获取指定委托信息

限频：每秒 1 次

### 请求地址

```
GET /deepcoin/trade/orderByID
```

### 请求参数

| 字段名 | 是否必填 | 类型   | 字段描述 |
| ------ | -------- | ------ | -------- |
| instId | 是       | string | 产品 ID  |
| ordId  | 是       | string | 订单 ID  |

### 请求示例

```json
{
  "instId": "BTC-USDT-SWAP",
  "ordId": "1001063720100637"
}
```



### 响应参数

| 字段名          | 类型   | 字段描述                                                     |
| --------------- | ------ | ------------------------------------------------------------ |
| instType        | string | 产品类型                                                     |
| instId          | string | 产品 ID                                                      |
| tgtCcy          | string | 市价单委托数量的类型 交易货币: `base_ccy` 计价货币: `quote_ccy`, 仅适用于币币订单 种 |
| ccy             | string | 保证金币种 仅适用于单币种保证金模式下的全仓币币杠杆订单      |
| ordId           | string | 订单 ID                                                      |
| clOrdId         | string | 客户自定义订单 ID                                            |
| tag             | string | 订单标签                                                     |
| px              | string | 委托价格                                                     |
| sz              | string | 委托数量                                                     |
| pnl             | string | 收益                                                         |
| ordType         | string | 订单类型 市价单: `market` 限价单: `limit` 只做 maker 单: `post_only` |
| side            | string | 订单方向 买: `buy` 卖: `sell`                                |
| posSide         | string | 持仓方向                                                     |
| tdMode          | string | 交易模式                                                     |
| accFillSz       | string | 累计成交数量                                                 |
| fillPx          | string | 最新成交价格                                                 |
| tradeId         | string | 最新成交 ID                                                  |
| fillSz          | string | 最新成交数量                                                 |
| fillTime        | string | 最新成交时间                                                 |
| avgPx           | string | 成交均价                                                     |
| state           | string | 订单状态 等待成交: `live` 部分成交: `partially_filled`       |
| lever           | string | 杠杆倍数 `0.01` 到 `125` 之间的数值 仅适用于 币币杠杆/永续   |
| tpTriggerPx     | string | 止盈触发价格                                                 |
| tpTriggerPxType | string | 止盈触发价格类型 最新价格: `last` 指数价格: `index` 标记价格: `mark` |
| tpOrdPx         | string | 止盈委托价格                                                 |
| slTriggerPx     | string | 止损触发价格                                                 |
| slTriggerPxType | string | 止损触发价格类型 最新价格: `last` 指数价格: `index` 标记价格: `mark` |
| slOrdPx         | string | 止损委托价格                                                 |
| feeCcy          | string | 交易手续费币种                                               |
| fee             | string | 交易手续费                                                   |
| rebateCcy       | string | 返佣金币种                                                   |
| source          | string | 订单来源                                                     |
| rebate          | string | 返佣金额 平台向达到指定 lv 交易等级的用户支付的挂单奖励(返佣) 如果没有返佣金 该字段为 “” 手续费返佣为正数 如 0.01 |
| category        | string | 订单种类                                                     |
| uTime           | string | 订单状态更新时间，Unix 时间戳的毫秒数格式                    |
| cTime           | string | 订单创建时间，Unix 时间戳的毫秒数格式                        |

### 响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": [
        {
            "instType": "SWAP",
            "instId": "BTC-USDT-SWAP",
            "tgtCcy": "",
            "ccy": "",
            "ordId": "1000587866808715",
            "clOrdId": "",
            "tag": "",
            "px": "1.000000",
            "sz": "95000.000000",
            "pnl": "0.000000",
            "ordType": "limit",
            "side": "buy",
            "posSide": "long",
            "tdMode": "cross",
            "accFillSz": "0.000000",
            "fillPx": "",
            "tradeId": "",
            "fillSz": "0.000000",
            "fillTime": "1739263130000",
            "avgPx": "",
            "state": "live",
            "lever": "1.000000",
            "tpTriggerPx": "",
            "tpTriggerPxType": "",
            "tpOrdPx": "",
            "slTriggerPx": "",
            "slTriggerPxType": "",
            "slOrdPx": "",
            "feeCcy": "USDT",
            "fee": "0.000000",
            "rebateCcy": "",
            "source": "",
            "rebate": "",
            "category": "normal",
            "uTime": "1739263130000",
            "cTime": "1739263130000"
        }
    ]
}
```

# 根据id获取指定历史委托信息

## 根据 id 获取指定历史委托信息

根据 id 获取指定委托信息

限频：每秒 1 次

### 请求地址

```
GET /deepcoin/trade/finishOrderByID
```

### 请求参数

| 字段名 | 是否必填 | 类型   | 字段描述 |
| ------ | -------- | ------ | -------- |
| instId | 是       | string | 产品 ID  |
| ordId  | 是       | string | 订单 ID  |

### 响应参数

| 字段名          | 类型   | 字段描述                                                     |
| --------------- | ------ | ------------------------------------------------------------ |
| instType        | string | 产品类型                                                     |
| instId          | string | 产品 ID                                                      |
| tgtCcy          | string | 市价单委托数量的类型 交易货币: `base_ccy` 计价货币: `;quote_ccy`, 仅适用于币币订单 |
| ccy             | string | 保证金币种 仅适用于单币种保证金模式下的全仓币币杠杆订单      |
| ordId           | string | 订单 ID                                                      |
| clOrdId         | string | 用户自定义订单 ID                                            |
| tag             | string | 订单标签                                                     |
| px              | string | 委托价格                                                     |
| sz              | string | 委托数量                                                     |
| pnl             | string | 收益                                                         |
| ordType         | string | 订单类型 市价单: `market` 限价单: `limit` 只做 maker 单: `post_only` |
| side            | string | 订单方向 买: `buy` 卖: `sell`                                |
| posSide         | string | 持仓方向                                                     |
| tdMode          | string | 交易模式                                                     |
| accFillSz       | string | 累计成交数量                                                 |
| fillPx          | string | 最新成交价格                                                 |
| tradeId         | string | 最新成交 ID                                                  |
| fillSz          | string | 最新成交数量                                                 |
| fillTime        | string | 最新成交时间                                                 |
| avgPx           | string | 平均成交价格                                                 |
| state           | string | 订单状态 等待成交: `live` 部分成交: `partially_filled`       |
| lever           | string | 杠杆倍数 `0.01` 到 `125` 之间的数值 仅适用于 币币杠杆/交割/永续 |
| tpTriggerPx     | string | 止盈触发价格                                                 |
| tpTriggerPxType | string | 止盈触发价类型 最新价格: `last` 指数价格: `index` 标记价格: `mark` |
| tpOrdPx         | string | 止盈委托价格                                                 |
| slTriggerPx     | string | 止损触发价格                                                 |
| slTriggerPxType | string | 止损触发价类型 最新价格: `last` 指数价格: `index` 标记价格: `mark` |
| slOrdPx         | string | 止损委托价格                                                 |
| feeCcy          | string | 交易手续费币种                                               |
| fee             | string | 交易手续费                                                   |
| rebateCcy       | string | 返佣币种                                                     |
| source          | string | 订单来源 网页端: `web` 手机端: `app` API 接口: `api` 系统: `system` |
| rebate          | string | 返佣金额 平台向达到指定 lv 交易等级的用户支付的挂单奖励(返佣) 如果没有返佣金 该字段为 “” 手续费返佣为正数 如 0.01 |
| category        | string | 订单种类 normal:普通委托;                                    |
| uTime           | string | 订单状态更新时间 Unix 时间戳的毫秒数格式                     |
| cTime           | string | 订单创建时间 Unix 时间戳的毫秒数格式                         |

### 响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": [
        {
            "instType": "SWAP",
            "instId": "BTC-USDT-SWAP",
            "tgtCcy": "",
            "ccy": "",
            "ordId": "1000587866272245",
            "clOrdId": "",
            "tag": "",
            "px": "1.000000",
            "sz": "95000.000000",
            "pnl": "0.000000",
            "ordType": "limit",
            "side": "buy",
            "posSide": "long",
            "tdMode": "cross",
            "accFillSz": "0.000000",
            "fillPx": "",
            "tradeId": "",
            "fillSz": "0.000000",
            "fillTime": "1739261771000",
            "avgPx": "",
            "state": "canceled",
            "lever": "1.000000",
            "tpTriggerPx": "",
            "tpTriggerPxType": "",
            "tpOrdPx": "",
            "slTriggerPx": "",
            "slTriggerPxType": "",
            "slOrdPx": "",
            "feeCcy": "USDT",
            "fee": "0.000000",
            "rebateCcy": "",
            "source": "",
            "rebate": "",
            "category": "normal",
            "uTime": "1739261771000",
            "cTime": "1739261762000"
        }
    ]
}
```

# 获取历史订单记录

## 获取历史订单记录

获取历史订单记录列表

限频：每秒 1 次

### 请求地址

```
GET /deepcoin/trade/orders-history
```

### 请求参数

| 字段名   | 是否必填 | 类型    | 字段描述                                                     |
| -------- | -------- | ------- | ------------------------------------------------------------ |
| instType | 是       | string  | 产品类型 现货: `SPOT` 合约: `SWAP`                           |
| instId   | 否       | string  | 产品 ID                                                      |
| ordType  | 否       | string  | 订单类型 市价单: `market` 限价单: `limit` 只做 maker 单: `post_only` |
| state    | 否       | string  | 订单状态 撤单成功: `canceled` 完全成交: `filled`             |
| after    | 否       | string  | 请求此 ID 之前（更旧的数据）的分页内容，传的值为对应接口的 ordId |
| before   | 否       | string  | 请求此 ID 之后（更新的数据）的分页内容，传的值为对应接口的 ordId |
| limit    | 否       | integer | 分页返回的结果集数量，最大为 `100`，不填默认返回 `100` 条    |
| ordId    | 否       | string  | 订单 ID                                                      |

### 响应参数

| 字段名          | 类型   | 字段描述                                                     |
| --------------- | ------ | ------------------------------------------------------------ |
| instType        | string | 产品类型                                                     |
| instId          | string | 产品 ID                                                      |
| tgtCcy          | string | 市价单委托数量的类型 交易货币: `base_ccy` 计价货币: `quote_ccy`, 仅适用于币币订单 种 |
| ccy             | string | 保证金币种 仅适用于单币种保证金模式下的全仓币币杠杆订单      |
| ordId           | string | 订单 ID                                                      |
| clOrdId         | string | 客户自定义订单 ID                                            |
| tag             | string | 订单标签                                                     |
| px              | string | 委托价格                                                     |
| sz              | string | 委托数量                                                     |
| pnl             | string | 收益                                                         |
| ordType         | string | 订单类型 市价单: `market` 限价单: `limit` 只做 maker 单: `post_only` |
| side            | string | 订单方向 买: `buy` 卖: `sell`                                |
| posSide         | string | 持仓方向                                                     |
| tdMode          | string | 交易模式                                                     |
| accFillSz       | string | 累计成交数量                                                 |
| fillPx          | string | 最新成交价格                                                 |
| tradeId         | string | 最新成交 ID                                                  |
| fillSz          | string | 最新成交数量                                                 |
| fillTime        | string | 最新成交时间                                                 |
| avgPx           | string | 成交均价                                                     |
| state           | string | 订单状态 等待成交: `live` 部分成交: `partially_filled`       |
| lever           | string | 杠杆倍数 `0.01` 到 `125` 之间的数值 仅适用于 币币杠杆/交割/永续 |
| tpTriggerPx     | string | 止盈触发价格                                                 |
| tpTriggerPxType | string | 止盈触发价格类型 last:最新价格;index:指数价格;mark:标记价格; |
| tpOrdPx         | string | 止盈委托价格                                                 |
| slTriggerPx     | string | 止损触发价格                                                 |
| slTriggerPxType | string | 止损触发价格类型 最新价格: `last` 指数价格: `index` 标记价格: `mark` |
| slOrdPx         | string | 止损委托价格                                                 |
| feeCcy          | string | 交易手续费币种                                               |
| fee             | string | 交易手续费                                                   |
| rebateCcy       | string | 返佣金币种                                                   |
| source          | string | 订单来源 13:策略委托单触发后的生成的限价单;                  |
| rebate          | string | 返佣金额 平台向达到指定 lv 交易等级的用户支付的挂单奖励(返佣) 如果没有返佣金 该字段为 “” 手续费返佣为正数 如 0.01 |
| category        | string | 订单种类                                                     |
| uTime           | string | 订单状态更新时间，Unix 时间戳的毫秒数格式                    |
| cTime           | string | 订单创建时间，Unix 时间戳的毫秒数格式                        |

### 响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": [
        {
            "instType": "SWAP",
            "instId": "BTC-USDT-SWAP",
            "tgtCcy": "",
            "ccy": "",
            "ordId": "1000587866072658",
            "clOrdId": "",
            "tag": "",
            "px": "90000",
            "sz": "300",
            "pnl": "0",
            "ordType": "limit",
            "side": "sell",
            "posSide": "short",
            "tdMode": "cross",
            "accFillSz": "300",
            "fillPx": "98230.5",
            "tradeId": "",
            "fillSz": "300",
            "fillTime": "1739261250000",
            "avgPx": "98230.5",
            "state": "filled",
            "lever": "1",
            "tpTriggerPx": "",
            "tpTriggerPxType": "",
            "tpOrdPx": "",
            "slTriggerPx": "",
            "slTriggerPxType": "",
            "slOrdPx": "",
            "feeCcy": "USDT",
            "fee": "8.840745",
            "rebateCcy": "",
            "source": "",
            "rebate": "",
            "category": "normal",
            "uTime": "1739261250000",
            "cTime": "1739261250000"
        }
    ]
}
```

# 获取未成交订单列表

## 获取当前账户下所有未成交订单信息

获取未成交订单

限频：每秒 1 次

### 请求地址

```
GET /deepcoin/trade/v2/orders-pending
```

### 请求参数

| 字段名 | 是否必填 | 类型    | 字段描述                                                 |
| ------ | -------- | ------- | -------------------------------------------------------- |
| instId | 是       | string  | 产品 ID                                                  |
| index  | 是       | integer | 页码                                                     |
| limit  | 否       | integer | 分页返回的结果集数量，最大为 `100`，不填默认返回 `30` 条 |
| ordId  | 否       | string  | 订单 ID                                                  |

### 响应参数

| 字段名          | 类型   | 字段描述                                                     |
| --------------- | ------ | ------------------------------------------------------------ |
| instType        | string | 产品类型                                                     |
| instId          | string | 产品 ID                                                      |
| tgtCcy          | string | 市价单委托数量的类型 交易货币: `base_ccy` 计价货币: `quote_ccy`, 仅适用于币币订单 种 |
| ccy             | string | 保证金币种 仅适用于单币种保证金模式下的全仓币币杠杆订单      |
| ordId           | string | 订单 ID                                                      |
| clOrdId         | string | 客户自定义订单 ID                                            |
| tag             | string | 订单标签                                                     |
| px              | string | 委托价格                                                     |
| sz              | string | 委托数量                                                     |
| pnl             | string | 收益                                                         |
| ordType         | string | 订单类型 市价单: `market` 限价单: `limit` 只做 maker 单: `post_only` |
| side            | string | 订单方向 买: `buy` 卖: `sell`                                |
| posSide         | string | 持仓方向                                                     |
| tdMode          | string | 交易模式                                                     |
| accFillSz       | string | 累计成交数量                                                 |
| fillPx          | string | 最新成交价格                                                 |
| tradeId         | string | 最新成交 ID                                                  |
| fillSz          | string | 最新成交数量                                                 |
| fillTime        | string | 最新成交时间                                                 |
| avgPx           | string | 成交均价                                                     |
| state           | string | 订单状态 等待成交: `live` 部分成交: `partially_filled`       |
| lever           | string | 杠杆倍数 `0.01` 到 `125` 之间的数值 仅适用于 币币杠杆/交割/永续 |
| tpTriggerPx     | string | 止盈触发价格                                                 |
| tpTriggerPxType | string | 止盈触发价格类型 last:最新价格;index:指数价格;mark:标记价格; |
| tpOrdPx         | string | 止盈委托价格                                                 |
| slTriggerPx     | string | 止损触发价格                                                 |
| slTriggerPxType | string | 止损触发价格类型 最新价格: `last` 指数价格: `index` 标记价格: `mark` |
| slOrdPx         | string | 止损委托价格                                                 |
| feeCcy          | string | 交易手续费币种                                               |
| fee             | string | 交易手续费                                                   |
| rebateCcy       | string | 返佣金币种                                                   |
| source          | string | 订单来源 13:策略委托单触发后的生成的限价单;                  |
| rebate          | string | 返佣金额 平台向达到指定 lv 交易等级的用户支付的挂单奖励(返佣) 如果没有返佣金 该字段为 “” 手续费返佣为正数 如 0.01 |
| category        | string | 订单种类                                                     |
| uTime           | string | 订单状态更新时间，Unix 时间戳的毫秒数格式                    |
| cTime           | string | 订单创建时间，Unix 时间戳的毫秒数格式                        |

### 响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": [
        {
            "instType": "SWAP",
            "instId": "BTC-USDT-SWAP",
            "tgtCcy": "",
            "ccy": "",
            "ordId": "1000587866072658",
            "clOrdId": "",
            "tag": "",
            "px": "90000",
            "sz": "300",
            "pnl": "0",
            "ordType": "limit",
            "side": "sell",
            "posSide": "short",
            "tdMode": "cross",
            "accFillSz": "300",
            "fillPx": "98230.5",
            "tradeId": "",
            "fillSz": "300",
            "fillTime": "1739261250000",
            "avgPx": "98230.5",
            "state": "filled",
            "lever": "1",
            "tpTriggerPx": "",
            "tpTriggerPxType": "",
            "tpOrdPx": "",
            "slTriggerPx": "",
            "slTriggerPxType": "",
            "slOrdPx": "",
            "feeCcy": "USDT",
            "fee": "8.840745",
            "rebateCcy": "",
            "source": "",
            "rebate": "",
            "category": "normal",
            "uTime": "1739261250000",
            "cTime": "1739261250000"
        }
    ]
}
```

# 资金费率

## 获取资金费率

获取合约交易对资金费率结算周期

限频：每秒 1 次

### 请求地址

```
GET /deepcoin/trade/funding-rate
```

### 请求参数

| 字段名   | 否必填 | 类型   | 字段描述                                           |
| -------- | ------ | ------ | -------------------------------------------------- |
| instType | 是     | string | 合约类型： U本位: `SwapU` 币本位: `Swap`           |
| instId   | 否     | string | 不为空时查询指定交易对资金费率周期，为空时查询所有 |

### 响应参数

| 字段名          | 类型    | 字段描述     |
| --------------- | ------- | ------------ |
| data            | array   |              |
| >settleInterval | integer | 资金费用间隔 |
| >instrumentID   | string  | 交易对       |
| >nextSettleTime | integer | 下次结算时间 |

### 响应示例

```text
{
    "code": "0",
    "msg": "",
    "data": [
        {
            "settleInterval": 28800,
            "instrumentID": "1000BABYDOGEUSDT",
            "nextSettleTime": 1739289600
        },
        {
            "settleInterval": 14400,
            "instrumentID": "1000CATUSDT",
            "nextSettleTime": 1739275200
        }
    ]
}
```

# 条件单下单

## 条件单下单

条件单是指当市场价格达到预设的触发价格时，系统自动下单的订单类型

限频：每秒 1 次

### 请求地址

```
POST /deepcoin/trade/trigger-order
```

### 请求参数

| 字段名          | 是否必填 | 类型   | 字段描述                                                     |
| --------------- | -------- | ------ | ------------------------------------------------------------ |
| instId          | 是       | string | 产品 ID                                                      |
| productGroup    | 是       | string | 交易类型 现货: `Spot` 永续: `Swap`                           |
| sz              | 是       | string | 委托数量                                                     |
| side            | 是       | string | 订单方向 买: `buy` 卖: `sell`                                |
| posSide         | 否       | string | 持仓方向 产品类型为 `SWAP` 时必填 多: `long` 空: `short`     |
| price           | 否       | string | 限价单价格 限价单时必填，市价单不需要                        |
| isCrossMargin   | 是       | string | 是否全仓 逐仓: `0` 全仓: `1`                                 |
| orderType       | 是       | string | 订单价格类型 限价: `limit` 市价: `market`                    |
| triggerPrice    | 是       | string | 条件单触发价格 当市场价格达到此价格时触发订单                |
| triggerPxType   | 否       | string | 触发价类型 最新价: `last` 指数价: `index` 标记价: `mark` 默认: `last` |
| mrgPosition     | 否       | string | 合并仓位 产品类型为 `SWAP` 时必填 合仓: `merge` 分仓: `split` |
| closePosId      | 否       | string | 平仓时指定的持仓ID 支持全仓和分仓模式                        |
| tdMode          | 是       | string | 交易模式 非保证金: `cash` 全仓: `cross` 逐仓: `isolated`     |
| tpTriggerPx     | 否       | number | 止盈触发价 条件单触发开仓后自动设置止盈订单                  |
| tpTriggerPxType | 否       | string | 止盈触发价类型 最新价: `last` 指数价: `index` 标记价: `mark` 默认: `last` |
| tpOrdPx         | 否       | number | 止盈委托价 `-1` 表示市价                                     |
| slTriggerPx     | 否       | number | 止损触发价 条件单触发开仓后自动设置止损订单                  |
| slTriggerPxType | 否       | string | 止损触发价类型 最新价: `last` 指数价: `index` 标记价: `mark` 默认: `last` |
| slOrdPx         | 否       | number | 止损委托价 `-1` 表示市价                                     |

### 请求示例

```json
// 场景1: 全仓合仓，开仓条件单市价
triggerOrder = &triggerOrderRequest{
    InstId:        "BTC-USDT-SWAP",
    ProductGroup:  "Swap",
    Sz:            "1",
    Side:          "buy",
    PosSide:       "long",
    IsCrossMargin: "1",
    OrderType:     "market", // 市价
    TriggerPrice:  "150000",
    MrgPosition:   "merge",
    TdMode:        "cross",
}

// 场景2: 全仓合仓，开仓条件限价单
triggerOrder = &triggerOrderRequest{
    InstId:        "BTC-USDT-SWAP",
    ProductGroup:  "Swap",
    Sz:            "1",
    Side:          "buy",
    PosSide:       "long",
    Price:         "140000",
    IsCrossMargin: "1",
    OrderType:     "limit", // 限价
    TriggerPrice:  "150000",
    MrgPosition:   "merge",
    TdMode:        "cross",
}

// 场景3: 全仓分仓，开仓条件单市价
triggerOrder = &triggerOrderRequest{
    InstId:        "BTC-USDT-SWAP",
    ProductGroup:  "Swap",
    Sz:            "1",
    Side:          "buy",
    PosSide:       "long",
    IsCrossMargin: "1",
    OrderType:     "market", // 市价
    TriggerPrice:  "150000",
    MrgPosition:   "split",
    TdMode:        "cross",
}

// 场景4: 全仓分仓，开仓条件限价单
triggerOrder = &triggerOrderRequest{
    InstId:        "BTC-USDT-SWAP",
    ProductGroup:  "Swap",
    Sz:            "1",
    Side:          "buy",
    PosSide:       "long",
    Price:         "140000",
    IsCrossMargin: "1",
    OrderType:     "limit", // 限价
    TriggerPrice:  "150000",
    MrgPosition:   "split",
    TdMode:        "cross",
}

// 场景5: 逐仓合仓，开仓条件单市价
triggerOrder = &triggerOrderRequest{
    InstId:        "BTC-USDT-SWAP",
    ProductGroup:  "Swap",
    Sz:            "1",
    Side:          "buy",
    PosSide:       "long",
    IsCrossMargin: "0",
    OrderType:     "market", // 市价
    TriggerPrice:  "150000",
    MrgPosition:   "merge",
    TdMode:        "isolated",
}

// 场景6: 逐仓合仓，开仓条件限价单
triggerOrder = &triggerOrderRequest{
    InstId:        "BTC-USDT-SWAP",
    ProductGroup:  "Swap",
    Sz:            "1",
    Side:          "buy",
    PosSide:       "long",
    Price:         "140000",
    IsCrossMargin: "0",
    OrderType:     "limit", // 限价
    TriggerPrice:  "150000",
    MrgPosition:   "merge",
    TdMode:        "isolated",
}

// 场景7: 逐仓分仓，开仓条件单市价
triggerOrder = &triggerOrderRequest{
    InstId:        "BTC-USDT-SWAP",
    ProductGroup:  "Swap",
    Sz:            "1",
    Side:          "buy",
    PosSide:       "long",
    IsCrossMargin: "0",
    OrderType:     "market", // 市价
    TriggerPrice:  "150000",
    MrgPosition:   "split",
    TdMode:        "isolated",
}

// 场景8: 逐仓分仓，开仓条件限价单
triggerOrder = &triggerOrderRequest{
    InstId:        "BTC-USDT-SWAP",
    ProductGroup:  "Swap",
    Sz:            "1",
    Side:          "buy",
    PosSide:       "long",
    Price:         "140000",
    IsCrossMargin: "0",
    OrderType:     "limit", // 限价
    TriggerPrice:  "150000",
    MrgPosition:   "split",
    TdMode:        "isolated",
}

// 场景9: 合约条件单，带止盈止损
triggerOrder = &triggerOrderRequest{
    InstId:          "BTC-USDT-SWAP",
    ProductGroup:    "Swap",
    Sz:              "1",
    Side:            "buy",
    PosSide:         "long",
    IsCrossMargin:   "1",
    OrderType:       "market",
    TriggerPrice:    "95000",
    TriggerPxType:   "last",
    MrgPosition:     "merge",
    TdMode:          "cross",
    TpTriggerPx:     100000,      // 止盈触发价
    TpTriggerPxType: "last",      // 止盈触发价类型
    TpOrdPx:         -1,          // 止盈委托价（市价）
    SlTriggerPx:     90000,       // 止损触发价
    SlTriggerPxType: "last",      // 止损触发价类型
    SlOrdPx:         -1,          // 止损委托价（市价）
}

// 场景10: 现货条件单，带止盈止损
triggerOrder = &triggerOrderRequest{
    InstId:          "BTC-USDT",
    ProductGroup:    "Spot",
    Sz:              "0.001",
    Side:            "buy",
    IsCrossMargin:   "1",
    OrderType:       "market",
    TriggerPrice:    "95000",
    TriggerPxType:   "last",
    TdMode:          "cash",
    TpTriggerPx:     100000,
    TpTriggerPxType: "last",
    TpOrdPx:         -1,
    SlTriggerPx:     90000,
    SlTriggerPxType: "last",
    SlOrdPx:         -1,
}

// 场景11: 仅设置止盈
triggerOrder = &triggerOrderRequest{
    InstId:          "BTC-USDT-SWAP",
    ProductGroup:    "Swap",
    Sz:              "1",
    Side:            "buy",
    PosSide:         "long",
    IsCrossMargin:   "1",
    OrderType:       "market",
    TriggerPrice:    "95000",
    MrgPosition:     "merge",
    TdMode:          "cross",
    TpTriggerPx:     100000,
    TpTriggerPxType: "last",
    TpOrdPx:         -1,
}

// 场景12: 仅设置止损
triggerOrder = &triggerOrderRequest{
    InstId:          "BTC-USDT-SWAP",
    ProductGroup:    "Swap",
    Sz:              "1",
    Side:            "sell",
    PosSide:         "short",
    IsCrossMargin:   "1",
    OrderType:       "market",
    TriggerPrice:    "95000",
    MrgPosition:     "merge",
    TdMode:          "cross",
    SlTriggerPx:     100000,
    SlTriggerPxType: "last",
    SlOrdPx:         -1,
}

// 场景13: 使用条件单平仓指定持仓（分仓模式）
triggerOrder = &triggerOrderRequest{
    InstId:        "BTC-USDT-SWAP",
    ProductGroup:  "Swap",
    Sz:            "1",
    Side:          "sell",
    PosSide:       "long",
    IsCrossMargin: "1",
    OrderType:     "market",
    TriggerPrice:  "105000",
    MrgPosition:   "split",
    TdMode:        "cross",
    ClosePosId:    "1001063717138767",  // 指定要平仓的持仓ID
}
```



### 响应参数

| 字段名  | 类型   | 字段描述                    |
| ------- | ------ | --------------------------- |
| ordId   | string | 订单 ID                     |
| clOrdId | string | 客户自定义订单 ID           |
| tag     | string | 订单标签                    |
| sCode   | string | 事件执行结果的状态码 0:成功 |
| sMsg    | string | 事件执行失败时的消息        |

### 响应示例

```json
{
  "code": "0",
  "msg": "",
  "data": {
    "ordId": "1000595855275418",
    "clOrdId": "",
    "tag": "",
    "sCode": "0",
    "sMsg": "Success"
  }
}
```



### 止盈止损功能说明

#### 功能概述

在下条件单时，可以选择性地设置止盈（TP）和/或止损（SL）参数。当条件单触发并开仓后，系统会自动为该持仓创建止盈止损订单。

#### 工作流程

```text
1. 用户下条件单，设置止盈止损参数
   ↓
2. 市场价格达到触发价格
   ↓
3. 条件单触发，执行开仓
   ↓
4. 系统自动为新开仓位设置止盈止损订单
```



#### 止盈止损参数

**止盈参数：**

- `tpTriggerPx`: 止盈触发价（设置止盈时必填）
- `tpTriggerPxType`: 触发价类型（`last`、`index` 或 `mark`），默认 `last`
- `tpOrdPx`: 止盈触发后的委托价，`-1` 表示市价单

**止损参数：**

- `slTriggerPx`: 止损触发价（设置止损时必填）
- `slTriggerPxType`: 触发价类型（`last`、`index` 或 `mark`），默认 `last`
- `slOrdPx`: 止损触发后的委托价，`-1` 表示市价单

#### 使用说明

1. **可选功能**：止盈止损参数为可选，您可以：
   - 同时设置止盈和止损
   - 仅设置止盈
   - 仅设置止损
   - 都不设置（标准条件单）
2. **价格关系**：
   - 做多仓位：止盈触发价 > 条件单触发价 > 止损触发价
   - 做空仓位：止损触发价 > 条件单触发价 > 止盈触发价
3. **触发时机**：止盈止损订单在条件单触发开仓后才会创建，不是在下条件单时立即创建
4. **市价 vs 限价**：
   - 设置 `tpOrdPx` 或 `slOrdPx` 为 `-1` 表示市价单
   - 设置具体价格表示限价单
5. **触发价类型**：
   - `last`: 最新成交价（默认）
   - `index`: 指数价格
   - `mark`: 标记价格
6. **支持市场**：现货（SPOT）和合约（SWAP）市场均支持条件单止盈止损

#### 示例说明

**示例1：做多仓位，完整止盈止损保护**

```json
{
  "instId": "BTC-USDT-SWAP",
  "productGroup": "Swap",
  "sz": "1",
  "side": "buy",
  "posSide": "long",
  "orderType": "market",
  "triggerPrice": "95000",
  "mrgPosition": "merge",
  "tdMode": "cross",
  "tpTriggerPx": 100000,
  "tpTriggerPxType": "last",
  "tpOrdPx": -1,
  "slTriggerPx": 90000,
  "slTriggerPxType": "last",
  "slOrdPx": -1
}
```



**示例2：现货买入，仅设置止盈**

```json
{
  "instId": "BTC-USDT",
  "productGroup": "Spot",
  "sz": "0.001",
  "side": "buy",
  "orderType": "market",
  "triggerPrice": "95000",
  "tdMode": "cash",
  "tpTriggerPx": 100000,
  "tpTriggerPxType": "last",
  "tpOrdPx": -1
}
```



**示例3：做空仓位，仅设置止损**

```json
{
  "instId": "BTC-USDT-SWAP",
  "productGroup": "Swap",
  "sz": "1",
  "side": "sell",
  "posSide": "short",
  "orderType": "market",
  "triggerPrice": "95000",
  "mrgPosition": "merge",
  "tdMode": "cross",
  "slTriggerPx": 100000,
  "slTriggerPxType": "last",
  "slOrdPx": -1
}
```



### 相关接口

- **设置持仓止盈止损**: `/deepcoin/trade/set-position-sltp` - 为已有持仓设置止盈止损
- **修改持仓止盈止损**: `/deepcoin/trade/modify-position-sltp` - 修改已有的止盈止损订单
- **取消持仓止盈止损**: `/deepcoin/trade/cancel-position-sltp` - 取消止盈止损订单
- **查询未触发条件单**: `/deepcoin/trade/trigger-orders-pending` - 查询已有的条件单

# 批量平仓

## 批量平仓

批量平仓指定产品的所有仓位，支持现货、币本位合约、U本位合约

限频：每秒 1 次

### 请求地址

```
POST /deepcoin/trade/batch-close-position
```

### 请求参数

| 字段名       | 是否必填 | 类型   | 字段描述                                          |
| ------------ | -------- | ------ | ------------------------------------------------- |
| productGroup | 是       | string | 产品组 现货: `Spot` 币本位: `Swap` U本位: `SwapU` |
| instId       | 是       | string | 产品 ID                                           |

### 请求示例

```json
// 批量平仓现货仓位
{
  "productGroup": "Spot",
  "instId": "BTC-USDT"
}

// 批量平仓币本位合约仓位
{
  "productGroup": "Swap",
  "instId": "BTC-USD-SWAP"
}

// 批量平仓U本位合约仓位
{
  "productGroup": "SwapU",
  "instId": "BTC-USDT-SWAP"
}
```



### 响应参数

| 字段名    | 类型  | 字段描述                         |
| --------- | ----- | -------------------------------- |
| errorList | array | 错误列表，包含平仓失败的详细信息 |

#### errorList 中的 ClosePositionErrorItem 结构

| 字段名        | 类型   | 字段描述    |
| ------------- | ------ | ----------- |
| memberId      | string | 会员 ID     |
| accountId     | string | 账户 ID     |
| tradeUnitId   | string | 交易单元 ID |
| instId        | string | 产品 ID     |
| posiDirection | string | 仓位方向    |
| errorCode     | int    | 错误码      |
| errorMsg      | string | 错误信息    |

### 响应示例

```json
// 成功响应（所有仓位都成功平仓）
{
  "code": "0",
  "msg": "",
  "data": {
    "errorList": []
  }
}

// 部分失败响应
{
  "code": "0",
  "msg": "",
  "data": {
    "errorList": [
      {
        "memberId": "10001",
        "accountId": "100001234",
        "tradeUnitId": "TU001",
        "instId": "BTC-USDT-SWAP",
        "posiDirection": "long",
        "errorCode": 51020,
        "errorMsg": "Insufficient position"
      },
      {
        "memberId": "10001",
        "accountId": "100001234",
        "tradeUnitId": "TU002",
        "instId": "BTC-USDT-SWAP",
        "posiDirection": "short",
        "errorCode": 51008,
        "errorMsg": "Order does not exist"
      }
    ]
  }
}
```



### 说明

#### 功能描述

- 批量平仓指定产品的所有仓位
- 支持现货(Spot)、币本位合约(Swap)、U本位合约(SwapU)
- 使用并发处理提高效率
- 返回错误列表，包含所有平仓失败的详细信息

#### 处理逻辑

1. 根据 `productGroup` 调用不同的服务（现货/合约）
2. 并发处理多个仓位的平仓操作
3. 收集所有平仓失败的错误信息
4. 即使部分仓位平仓失败，成功的仓位仍会被平仓

#### 注意事项

- 该接口会平仓指定产品的所有仓位，请谨慎使用

- 错误列表为空表示所有仓位都成功平仓

- 部分仓位平仓失败不会影响其他仓位的平仓操作

- # 当前资金费率

  ## 获取资金费率

  获取合约交易对的当前资金费率

  限频：每秒 1 次

  ### 请求地址

  ```
  GET /deepcoin/trade/fund-rate/current-funding-rate
  ```

  ### 请求参数

  | 字段名   | 否必填 | 类型   | 字段描述                                       |
  | -------- | ------ | ------ | ---------------------------------------------- |
  | instType | 是     | string | 合约类型： U本位: `SwapU` 币本位: `Swap`       |
  | instId   | 否     | string | 不为空时查询指定交易对资金费率，为空时查询所有 |

  ### 响应参数

  | 字段名              | 类型    | 字段描述 |
  | ------------------- | ------- | -------- |
  | >current_fund_rates | object  |          |
  | >fundingRate        | float64 | 资金费率 |
  | >instrumentID       | string  | 交易对   |

  ### 响应示例

  ```json
  {
      "code": "0",
      "msg": "",
      "data": {
          "current_fund_rates":[
              {
                  "instrumentId":"BTCUSD",
                  "fundingRate":0.00011794
                  }
              ]
              }
  }
  ```

# 资金费率

## 获取资金费率历史

获取合约交易对资金费率历史

限频：每秒 1 次

### 请求地址

```
GET /deepcoin/trade/fund-rate/history
```

### 请求参数

| 字段名 | 否必填 | 类型    | 字段描述                            |
| ------ | ------ | ------- | ----------------------------------- |
| instId | 是     | string  | 查询指定交易对资金费率周期          |
| page   | 否     | integer | 查询页数, 默认 `1`                  |
| size   | 否     | integer | 每页最大条数, 默认 `20`, 最大 `100` |

### 响应参数

| 字段名         | 类型    | 字段描述                                 |
| -------------- | ------- | ---------------------------------------- |
| code           | integer | 状态码                                   |
| msg            | string  | 错误信息                                 |
| data           | array   |                                          |
| >instrumentID  | string  | 交易对                                   |
| >CreateTime    | integer | 资金费率结算时间，Unix时间戳的毫秒数格式 |
| >rate          | string  | 资金费率                                 |
| >ratePeriodSec | integer | 资金费率结算周期（秒）                   |

### 响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": 
        {
            "list":[
            {
                "instrumentID":"BTCUSDT",
                "rate":"-0.00005",
                "CreateTime":1744606800,
                "ratePeriodSec":8
            },
            {
                "instrumentID":"BTCUSDT",
                "rate":"-0.00005",
                "CreateTime":1744606200,
                "ratePeriodSec":8
            },

    ]
}
}
```

# 修改开仓限价单止盈止损

## 修改开仓限价单止盈止损

修改开仓限价单止盈止损

限频：每秒 1 次

### 请求地址

```
POST /deepcoin/trade/replace-order-sltp
```

### 请求参数

| 字段名      | 是否必填 | 类型   | 字段描述                            |
| ----------- | -------- | ------ | ----------------------------------- |
| orderSysID  | 是       | string | 限价委托ID                          |
| tpTriggerPx | 否       | float  | 止盈价格，不传、或 0 值则是取消设置 |
| slTriggerPx | 否       | float  | 止损价格，不传、或 0 值则是取消设置 |

### 响应参数

无

### 响应示例

```json
// 修改成功
{
    "code": "0",
    "msg": "",
    "data": {

    }
}


// 修改失败
{
    "code": "24",
    "msg": "OrderNotFound:10005881114595391",
    "data": null
}
```

# 按仓位ID平仓

## 按仓位ID平仓

按指定的仓位ID列表平仓特定仓位，支持现货、币本位合约、U本位合约

限频：每秒 1 次

### 请求地址

```
POST /deepcoin/trade/close-position-by-ids
```

### 请求参数

| 字段名       | 是否必填 | 类型     | 字段描述                                          |
| ------------ | -------- | -------- | ------------------------------------------------- |
| productGroup | 是       | string   | 产品组 现货: `Spot` 币本位: `Swap` U本位: `SwapU` |
| instId       | 是       | string   | 产品 ID                                           |
| positionIds  | 是       | []string | 仓位 ID 列表，至少包含一个 ID                     |

### 请求示例

```json
// 平仓指定的现货仓位
{
  "productGroup": "Spot",
  "instId": "BTC-USDT",
  "positionIds": ["pos123", "pos456"]
}

// 平仓指定的币本位合约仓位
{
  "productGroup": "Swap",
  "instId": "BTC-USD-SWAP",
  "positionIds": ["pos789", "pos012", "pos345"]
}

// 平仓指定的U本位合约仓位
{
  "productGroup": "SwapU",
  "instId": "BTC-USDT-SWAP",
  "positionIds": ["pos678"]
}

// 平仓多个仓位
{
  "productGroup": "SwapU",
  "instId": "ETH-USDT-SWAP",
  "positionIds": [
    "1001063717138767",
    "1001063717138768",
    "1001063717138769",
    "1001063717138770"
  ]
}
```



### 响应参数

| 字段名    | 类型  | 字段描述                         |
| --------- | ----- | -------------------------------- |
| errorList | array | 错误列表，包含平仓失败的详细信息 |

#### errorList 中的 ClosePositionErrorItem 结构

| 字段名        | 类型   | 字段描述    |
| ------------- | ------ | ----------- |
| memberId      | string | 会员 ID     |
| accountId     | string | 账户 ID     |
| tradeUnitId   | string | 交易单元 ID |
| instId        | string | 产品 ID     |
| posiDirection | string | 仓位方向    |
| errorCode     | int    | 错误码      |
| errorMsg      | string | 错误信息    |

### 响应示例

```json
// 成功响应（所有指定仓位都成功平仓）
{
  "code": "0",
  "msg": "",
  "data": {
    "errorList": []
  }
}

// 部分失败响应
{
  "code": "0",
  "msg": "",
  "data": {
    "errorList": [
      {
        "memberId": "10001",
        "accountId": "100001234",
        "tradeUnitId": "TU001",
        "instId": "BTC-USDT-SWAP",
        "posiDirection": "long",
        "errorCode": 51020,
        "errorMsg": "Insufficient position"
      },
      {
        "memberId": "10001",
        "accountId": "100001234",
        "tradeUnitId": "TU002",
        "instId": "BTC-USDT-SWAP",
        "posiDirection": "short",
        "errorCode": 51404,
        "errorMsg": "Position does not exist"
      }
    ]
  }
}

// 全部失败响应
{
  "code": "0",
  "msg": "",
  "data": {
    "errorList": [
      {
        "memberId": "10001",
        "accountId": "100001234",
        "tradeUnitId": "TU001",
        "instId": "BTC-USDT-SWAP",
        "posiDirection": "long",
        "errorCode": 51404,
        "errorMsg": "Position does not exist"
      },
      {
        "memberId": "10001",
        "accountId": "100001234",
        "tradeUnitId": "TU002",
        "instId": "BTC-USDT-SWAP",
        "posiDirection": "short",
        "errorCode": 51404,
        "errorMsg": "Position does not exist"
      }
    ]
  }
}
```



### 说明

#### 功能描述

- 按指定的仓位 ID 列表平仓特定仓位
- 支持现货(Spot)、币本位合约(Swap)、U本位合约(SwapU)
- 可以一次性平仓多个指定的仓位
- 使用并发处理提高效率

#### 处理逻辑

1. 内部调用与批量平仓相同的 `doClosePositionInternal` 方法
2. 通过 `positionIds` 参数过滤，只平仓指定 ID 的仓位
3. 并发处理多个仓位的平仓操作
4. 收集所有平仓失败的错误信息

#### 注意事项

- `positionIds` 必须至少包含一个仓位 ID

- 只会平仓列表中指定的仓位，不会影响其他仓位

- 错误列表为空表示所有指定仓位都成功平仓

- 部分仓位平仓失败不会影响其他仓位的平仓操作

- 如果仓位 ID 不存在或已被平仓，会在错误列表中返回相应错误信息

- # 设置持仓止盈止损

  ## 设置持仓止盈止损

  为已有持仓设置止盈止损，支持现货和合约交易。

  限频：每秒 1 次

  限速规则：UserID

  ### 请求地址

  ```
  POST /deepcoin/trade/set-position-sltp
  ```

  ### 请求参数

  | 字段名          | 是否必填 | 类型   | 字段描述                                                     |
  | --------------- | -------- | ------ | ------------------------------------------------------------ |
  | instType        | 是       | string | 产品类型 现货: `SPOT` 合约: `SWAP`                           |
  | instId          | 是       | string | 产品ID 例如：现货 `BTC-USDT`，合约 `BTC-USDT-SWAP`           |
  | posSide         | 否       | string | 持仓方向（合约必填） 多头: `long` 空头: `short`              |
  | mrgPosition     | 否       | string | 保证金仓位模式（合约） 合仓: `merge` 分仓: `split`           |
  | tdMode          | 否       | string | 交易模式（合约） 全仓: `cross` 逐仓: `isolated`              |
  | posId           | 否       | string | 仓位ID（当 mrgPosition 为 `split` 时必填）                   |
  | tpTriggerPx     | 否       | string | 止盈触发价 止盈和止损至少填写一个                            |
  | tpTriggerPxType | 否       | string | 止盈触发价类型 最新价: `last` 指数价: `index` 标记价: `mark` 默认: `last` |
  | tpOrdPx         | 否       | string | 止盈委托价 `-1` 表示市价 默认: `-1`                          |
  | slTriggerPx     | 否       | string | 止损触发价 止盈和止损至少填写一个                            |
  | slTriggerPxType | 否       | string | 止损触发价类型 最新价: `last` 指数价: `index` 标记价: `mark` 默认: `last` |
  | slOrdPx         | 否       | string | 止损委托价 `-1` 表示市价 默认: `-1`                          |
  | sz              | 否       | string | 持仓数量，用于部分止盈止损 不填表示全部持仓                  |

  **注意事项**:

  - `tpTriggerPx` 和 `slTriggerPx` 至少需要提供一个
  - 合约交易在分仓模式下（`mrgPosition=split`），必须提供 `posId`
  - 现货交易不需要填写 `posSide`、`mrgPosition`、`tdMode` 和 `posId`

  ### 请求示例

  **现货 - 同时设置止盈和止损：**

  ```json
  {
    "instType": "SPOT",
    "instId": "BTC-USDT",
    "tpTriggerPx": "107000",
    "slTriggerPx": "102000"
  }
  ```

  

  **合约 - 为多头仓位设置止盈止损（合仓模式）：**

  ```json
  {
    "instType": "SWAP",
    "instId": "BTC-USDT-SWAP",
    "posSide": "long",
    "mrgPosition": "merge",
    "tdMode": "cross",
    "tpTriggerPx": "107000",
    "slTriggerPx": "102000"
  }
  ```

  

  **合约 - 为特定仓位设置止盈止损（分仓模式）：**

  ```json
  {
    "instType": "SWAP",
    "instId": "BTC-USDT-SWAP",
    "posSide": "long",
    "mrgPosition": "split",
    "tdMode": "isolated",
    "posId": "1000596063679172",
    "tpTriggerPx": "107000",
    "tpTriggerPxType": "mark",
    "tpOrdPx": "-1",
    "slTriggerPx": "102000",
    "slTriggerPxType": "mark",
    "slOrdPx": "-1"
  }
  ```

  

  **仅设置止盈：**

  ```json
  {
    "instType": "SPOT",
    "instId": "BTC-USDT",
    "tpTriggerPx": "107000"
  }
  ```

  

  **仅设置止损：**

  ```json
  {
    "instType": "SPOT",
    "instId": "BTC-USDT",
    "slTriggerPx": "102000"
  }
  ```

  

  ### 响应参数

  | 字段名 | 类型   | 字段描述                       |
  | ------ | ------ | ------------------------------ |
  | ordId  | string | 止盈止损订单ID（用于取消订单） |
  | sCode  | string | 事件执行结果的状态码 `0`: 成功 |
  | sMsg   | string | 事件执行失败时的消息           |

  ### 响应示例

  **成功响应：**

  ```json
  {
    "code": "0",
    "msg": "",
    "data": {
      "ordId": "1001063717138767",
      "sCode": "0",
      "sMsg": ""
    }
  }
  ```

  

  **失败响应：**

  ```json
  {
    "code": "51000",
    "msg": "参数错误",
    "data": {
      "ordId": "",
      "sCode": "51000",
      "sMsg": "止盈和止损至少需要设置一个"
    }
  }
  ```

  

  ### 说明

  #### 功能说明

  - 为已有持仓设置止盈和/或止损
  - 支持现货（SPOT）和合约（SWAP）交易
  - 通过指定 `sz` 参数可以实现部分仓位止盈止损
  - 支持不同的触发价类型（最新价、指数价、标记价）
  - 可以设置市价或限价委托执行止盈止损

  #### 使用场景

  1. **风险管理**：当价格达到目标或止损位时自动平仓
  2. **利润保护**：当价格达到预期水平时锁定利润
  3. **损失限制**：通过设置止损限制潜在损失
  4. **部分仓位管理**：仅对部分仓位设置止盈止损

  #### 重要提示

  1. **订单ID**：保存返回的 `ordId` 以便后续取消或修改止盈止损订单
  2. **价格精度**：触发价格必须符合产品的价格精度要求
  3. **仓位验证**：设置止盈止损前需确保有对应的持仓
  4. **覆盖规则**：设置新的止盈止损可能会覆盖同一仓位的现有止盈止损订单
  5. **合约特殊性**：合约交易需要正确指定持仓方向（`posSide`）和保证金模式

  #### 相关接口

  - **修改持仓止盈止损**：`/deepcoin/trade/modify-position-sltp` - 修改已设置的止盈止损订单
  - **取消持仓止盈止损**：`/deepcoin/trade/cancel-position-sltp` - 取消止盈止损订单
  - **查询待成交条件单**：`/deepcoin/trade/trigger-orders-pending` - 查询现有止盈止损订单

# 取消持仓止盈止损

## 取消持仓止盈止损

取消已设置的持仓止盈止损订单，支持现货和合约交易。

限频：每秒 1 次

限速规则：UserID

### 请求地址

```
POST /deepcoin/trade/cancel-position-sltp
```

### 请求参数

| 字段名   | 是否必填 | 类型   | 字段描述                                           |
| -------- | -------- | ------ | -------------------------------------------------- |
| instType | 是       | string | 产品类型 现货: `SPOT` 合约: `SWAP`                 |
| instId   | 是       | string | 产品ID 例如：现货 `BTC-USDT`，合约 `BTC-USDT-SWAP` |
| ordId    | 是       | string | 止盈止损订单ID 通过设置接口返回或查询条件单获取    |

**注意事项**:

- `ordId` 是通过 `set-position-sltp` API 设置止盈止损时返回的订单ID
- 也可以通过查询待成交条件单来获取 `ordId`

### 请求示例

**取消现货持仓止盈止损：**

```json
{
  "instType": "SPOT",
  "instId": "BTC-USDT",
  "ordId": "1000762096073860"
}
```



**取消合约持仓止盈止损：**

```json
{
  "instType": "SWAP",
  "instId": "BTC-USDT-SWAP",
  "ordId": "1000596068909100"
}
```



### 响应参数

| 字段名 | 类型   | 字段描述                       |
| ------ | ------ | ------------------------------ |
| ordId  | string | 订单ID                         |
| sCode  | string | 事件执行结果的状态码 `0`: 成功 |
| sMsg   | string | 事件执行失败时的消息           |

### 响应示例

**成功响应：**

```json
{
  "code": "0",
  "msg": "",
  "data": {
    "ordId": "1000762096073860",
    "sCode": "0",
    "sMsg": ""
  }
}
```



**失败响应（订单不存在）：**

```json
{
  "code": "51400",
  "msg": "订单不存在",
  "data": {
    "ordId": "1000762096073860",
    "sCode": "51400",
    "sMsg": "订单不存在"
  }
}
```



**失败响应（订单已执行）：**

```json
{
  "code": "51401",
  "msg": "订单已执行",
  "data": {
    "ordId": "1000762096073860",
    "sCode": "51401",
    "sMsg": "订单已执行或已取消"
  }
}
```



### 说明

#### 功能说明

- 取消已设置的持仓止盈止损订单
- 支持现货（SPOT）和合约（SWAP）交易
- 只能取消待成交的止盈止损订单（尚未触发）

#### 使用场景

1. **策略调整**：取消现有止盈止损以设置新的价格水平
2. **市场变化应对**：当市场条件变化时移除止盈止损
3. **手动控制**：改为手动控制仓位平仓而非自动止盈止损
4. **错误纠正**：取消错误设置的止盈止损订单

#### 重要提示

1. **订单ID必需**：必须有 set-position-sltp 响应中返回的 `ordId`
2. **订单状态**：只能取消待成交订单；已触发或已执行的订单无法取消
3. **查询订单**：使用 trigger-orders-pending API 查询现有止盈止损订单并获取其ID
4. **时机把握**：一旦止盈止损订单被触发，就无法取消
5. **验证确认**：取消前请确保订单属于您的账户

#### 相关接口

- **设置持仓止盈止损**：`/deepcoin/trade/set-position-sltp` - 设置新的止盈止损订单
- **修改持仓止盈止损**：`/deepcoin/trade/modify-position-sltp` - 修改已设置的止盈止损订单
- **查询待成交条件单**：`/deepcoin/trade/trigger-orders-pending` - 查询现有止盈止损订单
- **查询条件单历史**：`/deepcoin/trade/trigger-orders-history` - 查询历史止盈止损订单

# 修改持仓止盈止损

## 修改持仓止盈止损

修改已设置的持仓止盈止损订单，支持现货和合约交易。

限频：每秒 1 次

限速规则：UserID

### 请求地址

```
POST /deepcoin/trade/modify-position-sltp
```

### 请求参数

| 字段名          | 是否必填 | 类型   | 字段描述                                                     |
| --------------- | -------- | ------ | ------------------------------------------------------------ |
| instType        | 是       | string | 产品类型 现货: `SPOT` 合约: `SWAP`                           |
| instId          | 是       | string | 产品ID 例如：现货 `BTC-USDT`，合约 `BTC-USDT-SWAP`           |
| ordId           | 是       | string | 止盈止损订单ID（从 set-position-sltp 接口响应中获取）        |
| posSide         | 否       | string | 持仓方向（合约必填） 多头: `long` 空头: `short`              |
| mrgPosition     | 否       | string | 保证金仓位模式（合约） 合仓: `merge` 分仓: `split`           |
| tdMode          | 否       | string | 交易模式（合约） 全仓: `cross` 逐仓: `isolated`              |
| posId           | 否       | string | 仓位ID（当 mrgPosition 为 `split` 时必填）                   |
| tpTriggerPx     | 否       | string | 止盈触发价 止盈和止损至少填写一个                            |
| tpTriggerPxType | 否       | string | 止盈触发价类型 最新价: `last` 指数价: `index` 标记价: `mark` 默认: `last` |
| tpOrdPx         | 否       | string | 止盈委托价 `-1` 表示市价 默认: `-1`                          |
| slTriggerPx     | 否       | string | 止损触发价 止盈和止损至少填写一个                            |
| slTriggerPxType | 否       | string | 止损触发价类型 最新价: `last` 指数价: `index` 标记价: `mark` 默认: `last` |
| slOrdPx         | 否       | string | 止损委托价 `-1` 表示市价 默认: `-1`                          |
| sz              | 否       | string | 持仓数量，用于部分止盈止损 不填表示全部持仓                  |

**注意事项**:

- `ordId` 为必填项，必须是有效的待成交止盈止损订单ID
- `tpTriggerPx` 和 `slTriggerPx` 至少需要提供一个
- 合约交易在分仓模式下（`mrgPosition=split`），必须提供 `posId`
- 现货交易不需要填写 `posSide`、`mrgPosition`、`tdMode` 和 `posId`
- 订单ID从 `set-position-sltp` 接口的响应中获取

### 请求示例

**现货 - 同时修改止盈和止损：**

```json
{
  "instType": "SPOT",
  "instId": "BTC-USDT",
  "ordId": "1000762096073860",
  "tpTriggerPx": "110000",
  "slTriggerPx": "103000"
}
```



**合约 - 修改多头仓位止盈止损（合仓模式）：**

```json
{
  "instType": "SWAP",
  "instId": "BTC-USDT-SWAP",
  "ordId": "1000596069447069",
  "posSide": "long",
  "mrgPosition": "merge",
  "tdMode": "cross",
  "tpTriggerPx": "110000",
  "tpTriggerPxType": "mark",
  "tpOrdPx": "-1",
  "slTriggerPx": "103000",
  "slTriggerPxType": "mark",
  "slOrdPx": "-1"
}
```



**合约 - 修改特定仓位止盈止损（分仓模式）：**

```json
{
  "instType": "SWAP",
  "instId": "BTC-USDT-SWAP",
  "ordId": "1000596069492933",
  "posSide": "long",
  "mrgPosition": "split",
  "tdMode": "isolated",
  "posId": "1000596069432784",
  "tpTriggerPx": "111000",
  "tpTriggerPxType": "mark",
  "tpOrdPx": "-1",
  "slTriggerPx": "104000",
  "slTriggerPxType": "mark",
  "slOrdPx": "-1",
  "sz": "200"
}
```



**仅修改止盈：**

```json
{
  "instType": "SWAP",
  "instId": "BTC-USDT-SWAP",
  "ordId": "1000596069447069",
  "posSide": "long",
  "mrgPosition": "merge",
  "tdMode": "cross",
  "tpTriggerPx": "112000",
  "tpTriggerPxType": "mark",
  "tpOrdPx": "-1"
}
```



**仅修改止损：**

```json
{
  "instType": "SWAP",
  "instId": "BTC-USDT-SWAP",
  "ordId": "1000596069447069",
  "posSide": "long",
  "mrgPosition": "merge",
  "tdMode": "cross",
  "slTriggerPx": "101000",
  "slTriggerPxType": "mark",
  "slOrdPx": "-1"
}
```



### 响应参数

| 字段名 | 类型   | 字段描述                       |
| ------ | ------ | ------------------------------ |
| ordId  | string | 止盈止损订单ID                 |
| sCode  | string | 事件执行结果的状态码 `0`: 成功 |
| sMsg   | string | 事件执行失败时的消息           |

### 响应示例

**成功响应：**

```json
{
  "code": "0",
  "msg": "",
  "data": {
    "ordId": "1000596069447069",
    "sCode": "0",
    "sMsg": ""
  }
}
```



**失败响应：**

```json
{
  "code": "51400",
  "msg": "订单不存在",
  "data": {
    "ordId": "",
    "sCode": "51400",
    "sMsg": "订单不存在或已被执行"
  }
}
```



### 说明

#### 功能说明

- 修改已设置的持仓止盈和/或止损订单
- 支持现货（SPOT）和合约（SWAP）交易
- 通过指定 `sz` 参数可以修改部分仓位止盈止损
- 支持不同的触发价类型（最新价、指数价、标记价）
- 可以修改市价或限价委托执行止盈止损
- 可以单独修改止盈或止损

#### 使用场景

1. **策略调整**：根据市场情况调整止盈止损水平
2. **风险管理**：根据持仓表现收紧或放宽止损
3. **利润优化**：随着价格有利变动调整止盈目标
4. **部分仓位管理**：仅修改部分仓位的止盈止损

#### 重要提示

1. **订单ID必需**：必须提供从 set-position-sltp 响应中获取的有效 `ordId`
2. **订单状态**：只能修改待成交的止盈止损订单（尚未触发或执行）
3. **价格精度**：触发价格必须符合产品的价格精度要求
4. **参数一致性**：`instId`、`posSide`、`mrgPosition` 等参数应与原订单一致
5. **至少修改一个**：必须修改止盈或止损中的至少一个
6. **分仓模式**：分仓模式下必须提供 `posId`
7. **查询订单**：使用 trigger-orders-pending 接口查询现有止盈止损订单并获取订单ID

#### 相关接口

- **设置持仓止盈止损**：`/deepcoin/trade/set-position-sltp` - 创建新的止盈止损订单
- **取消持仓止盈止损**：`/deepcoin/trade/cancel-position-sltp` - 取消止盈止损订单
- **查询待成交条件单**：`/deepcoin/trade/trigger-orders-pending` - 查询现有止盈止损订单

#### 常见错误

| 错误码 | 错误信息                   | 解决方案                                     |
| ------ | -------------------------- | -------------------------------------------- |
| 51400  | 订单不存在                 | 检查订单ID是否正确，订单是否已被取消或执行   |
| 51000  | 参数错误                   | 检查必填参数是否完整，参数格式是否正确       |
| 51001  | 止盈和止损至少需要设置一个 | 至少提供 tpTriggerPx 或 slTriggerPx 其中一个 |

# 查询未触发条件单

## 查询未触发条件单

查询当前账户下所有未触发的条件单

限频：每秒 1 次

### 请求地址

```
GET /deepcoin/trade/trigger-orders-pending
```

### 请求参数

| 字段名    | 是否必填 | 类型    | 字段描述                                                     |
| --------- | -------- | ------- | ------------------------------------------------------------ |
| instType  | 是       | string  | 产品类型 币币: `SPOT` 合约: `SWAP`                           |
| instId    | 是       | string  | 产品 ID，如 `BTC-USDT-SWAP`                                  |
| orderType | 否       | string  | 触发订单类型 限价单: `limit` 市价单: `market`                |
| limit     | 否       | integer | 分页返回的结果集数量，最大为 `100`，不填默认返回 `100` 条，取值范围：1-100 |

### 响应参数

| 字段名              | 类型   | 字段描述                                                     |
| ------------------- | ------ | ------------------------------------------------------------ |
| instType            | string | 产品类型，如 `SWAP`                                          |
| instId              | string | 产品 ID，如 `BTC-USDT-SWAP`                                  |
| ordId               | string | 订单 ID                                                      |
| triggerPx           | string | 触发价格                                                     |
| ordPx               | string | 委托价格                                                     |
| sz                  | string | 委托数量                                                     |
| ordType             | string | 订单类型 市价单: `market` 限价单: `limit`                    |
| side                | string | 订单方向 买: `buy` 卖: `sell`                                |
| posSide             | string | 持仓方向 多头: `long` 空头: `short`                          |
| tdMode              | string | 交易模式 全仓: `cross` 逐仓: `isolated`                      |
| triggerOrderType    | string | 触发订单类型 `TPSL`: 止盈止损 `Conditional`: 条件单 `Serial`: 连续下单 `Indicator`: 指标单 `Complex`: 组合指标 `Tracking`: 追踪出场 `Line`: 画线委托 |
| triggerPxType       | string | 触发价类型 最新价: `last` 指数价: `index` 标记价: `mark`     |
| lever               | string | 杠杆倍数                                                     |
| slPrice             | string | 止损价格                                                     |
| slTriggerPrice      | string | 止损触发价格                                                 |
| tpPrice             | string | 止盈价格                                                     |
| tpTriggerPrice      | string | 止盈触发价格                                                 |
| closeSLTriggerPrice | string | 开仓止损价格                                                 |
| closeTPTriggerPrice | string | 开仓止盈价格                                                 |
| cTime               | string | 订单创建时间，Unix 时间戳的毫秒数格式                        |
| uTime               | string | 订单状态更新时间，Unix 时间戳的毫秒数格式                    |

### 响应示例

```json
{
    "code": "0",
    "msg": "",
    "data": [
        {
            "instType": "SWAP",
            "instId": "BTC-USDT-SWAP",
            "ordId": "1000595888037394",
            "triggerPx": "0",
            "ordPx": "0",
            "sz": "0",
            "ordType": "",
            "side": "sell",
            "posSide": "long",
            "tdMode": "cross",
            "triggerOrderType": "TPSL",
            "triggerPxType": "last",
            "lever": "11",
            "slPrice": "0",
            "slTriggerPrice": "110001",
            "tpPrice": "0",
            "tpTriggerPrice": "170001",
            "closeSLTriggerPrice": "",
            "closeTPTriggerPrice": "",
            "cTime": "1758028926000",
            "uTime": "1758028926000"
        },
        {
            "instType": "SWAP",
            "instId": "BTC-USDT-SWAP",
            "ordId": "1000595888000274",
            "triggerPx": "150001",
            "ordPx": "130001",
            "sz": "201",
            "ordType": "",
            "side": "buy",
            "posSide": "long",
            "tdMode": "cross",
            "triggerOrderType": "Conditional",
            "triggerPxType": "last",
            "lever": "11",
            "slPrice": "130001",
            "slTriggerPrice": "150001",
            "tpPrice": "0",
            "tpTriggerPrice": "0",
            "closeSLTriggerPrice": "",
            "closeTPTriggerPrice": "",
            "cTime": "1758026859000",
            "uTime": "1758026859000"
        },
        {
            "instType": "SWAP",
            "instId": "BTC-USDT-SWAP",
            "ordId": "1000595887990299",
            "triggerPx": "150000",
            "ordPx": "130000",
            "sz": "200",
            "ordType": "",
            "side": "buy",
            "posSide": "long",
            "tdMode": "cross",
            "triggerOrderType": "Conditional",
            "triggerPxType": "last",
            "lever": "11",
            "slPrice": "",
            "slTriggerPrice": "",
            "tpPrice": "",
            "tpTriggerPrice": "",
            "closeSLTriggerPrice": "110000",
            "closeTPTriggerPrice": "160000",
            "cTime": "1758026306000",
            "uTime": "1758026306000"
        }
    ]
}
```

# WebSocket 私有频道

### WebSocket 私有频道

```
主网: wss://stream.deepcoin.com/v1/private
```

### 获取 listenkey

HTTP 方式: `GET`

HTTP 请求URL: `/deepcoin/listenkey/acquire`

#### response:

```json
{
  "code": "0",
  "msg": "",
  "data": {
    "listenkey": "a29e6d260bb2a82478abf49759cb31a9",
    "expire_time": 1691403285
  }
}
```



### 延长过期时间

滑动窗口，往后续期一小时

HTTP 方式: `GET`

HTTP 请求URL: `/deepcoin/listenkey/extend`

```
body listenkey="f24739a259bc1ac714dad2ac6690c816"
```

#### response:

```json
{
  "code": "0",
  "msg": "",
  "data": {
    "listenkey": "a29e6d260bb2a82478abf49759cb31a9",
    "expire_time": 1691403285
  }
}
```



### ws 订阅

```
wss://stream.deepcoin.com/v1/private?listenKey=404879eae0a969e199d2bc3f3766faa1
```

### 返回参数

目前只要订阅成功，则会将资金变动、订单变动等一次推送报单通知

## 报单通知

### 响应参数

| 字段名         | 类型   | 示例值             | 简化字段名 | 字段描述         |
| -------------- | ------ | ------------------ | ---------- | ---------------- |
| LocalID        | string | ""                 | L          | 报单本地标识     |
| InstrumentID   | string | "BTCUSDT"          | I          | 标的代码         |
| OrderPriceType | string | "9"                | OPT        | 报单价格类型     |
| Direction      | string | "0"                | D          | 买卖方向         |
| OffsetFlag     | string | 0                  | o          | 开平标志         |
| Price          | float  | 30027.5            | P          | 报单价格         |
| Volume         | int    | 1                  | V          | 数量             |
| OrderType      | string | "0"                | OT         | 订单类型         |
| IsCrossMargin  | int    | 1                  | i          | 是否全仓         |
| OrderSysID     | string | "1000466073187710" | OS         | 报单系统唯一代码 |
| Leverage       | int    | 125                | l          | 委托单杠杆倍数   |
| OrderStatus    | string | "1"                | Or         | 报单状态         |
| VolumeTraded   | int    | 1                  | v          | 成交数量         |
| InsertTime     | int    | 1689727080         | IT         | 插入时间         |
| UpdateTime     | int    | 1689727080         | U          | 更新时间         |
| Turnover       | float  | 30.0275            | T          | 成交金额         |
| PosiDirection  | string | "0"                | p          | 持仓多空方向     |
| TradePrice     | float  | 30027.5            | t          | 成交均价         |

### 响应示例

```json
{
  "action": "PushOrder",
  "result": [
    {
      "table": "Order",
      "data": {
        "D": "1",
        "I": "BTCUSDT",
        "IT": 1690804738,
        "L": "1000175061255804",
        "O": "9",
        "OS": "1000175061255804",
        "OT": "0",
        "Or": "1",
        "P": 29365,
        "T": 1616.621,
        "U": 1690804738,
        "V": 55,
        "i": 0,
        "l": 125,
        "o": "0",
        "p": "1",
        "t": 29393.1090909091,
        "v": 55
      }
    }
  ]
}
```

# 资金通知

## 资金通知

### 响应参数

| 字段名       | 类型   | 示例值      | 简化字段名 | 字段描述       |
| ------------ | ------ | ----------- | ---------- | -------------- |
| AccountID    | string | "8644930"   | A          | 资金账号       |
| Currency     | string | "BCH"       | C          | 币种           |
| MemberID     | string | "8644930"   | M          | 成员代码       |
| Available    | float  | 1.020878361 | a          | 可用资金       |
| Withdrawable | float  | 1.020878361 | W          | 可取资金       |
| Balance      | float  | 1.05827892  | B          | 静态权益       |
| UseMargin    | float  | 0.037400559 | u          | 所有占用保证金 |
| CloseProfit  | float  | 0.19237793  | CP         | 平仓盈亏       |
| FrozenMargin | int    | 0           | FM         | 冻结保证金     |
| FrozenFee    | int    | 0           | FF         | 冻结手续费     |

### 响应示例

```json
{
  "action": "PushAccount",
  "result": [
    {
      "table": "Account",
      "data": {
        "A": "36005550",
        "B": 1998332.7691469,
        "C": "USDT",
        "M": "36005550",
        "W": 1998316.543355371,
        "a": 1998316.543355371,
        "c": 2.02499997,
        "u": 12.932968
      }
    }
  ]
}
```

# 持仓通知

## 持仓通知

### 响应参数

| 字段名        | 类型   | 示例值      | 简化字段名 | 字段描述     |
| ------------- | ------ | ----------- | ---------- | ------------ |
| MemberID      | string | 455725      | M          | 成员代码     |
| InstrumentID  | string | ETHUSD      | I          | 标的代码     |
| PosiDirection | string | 1           | p          | 持仓多空方向 |
| Position      | int    | 40          | Po         | 总持仓       |
| UseMargin     | float  | 0.108207952 | u          | 占用保证金   |
| CloseProfit   | int    | 0           | CP         | 平仓盈亏     |
| OpenPrice     | int    | 1779.275975 | OP         | 开仓均价     |
| Leverage      | int    | 2           | l          | 杠杆倍数     |
| AccountID     | string | "455725"    | A          | 资金账号     |
| IsCrossMargin | int    | 0           | i          | 是否全仓     |
| UpdateTime    | int    | 1683885945  | U          | 更新时间     |

### 响应示例

```json
{
  "action": "PushPosition",
  "result": [
    {
      "table": "Position",
      "data": {
        "A": "36005550",
        "I": "BTCUSDT",
        "M": "36005550",
        "OP": 29393.1090909091,
        "Po": 55,
        "U": 1690804738,
        "c": 0,
        "i": 0,
        "l": 125,
        "p": "1",
        "u": 12.932968
      }
    }
  ]
}
```

# 成交通知

## 成交通知

### 响应参数

| 字段名        | 类型   | 示例值             | 简化字段名 | 字段描述                 |
| ------------- | ------ | ------------------ | ---------- | ------------------------ |
| TradeID       | string | "1000265430292943" | TI         | 成交代码                 |
| Direction     | string | "0"                | D          | 买卖方向                 |
| OrderSysID    | string | "1000466047366963" | OS         | 报单系统唯一代码(待删除) |
| MemberID      | string | "9052130"          | M          | 成员代码                 |
| AccountID     | string | "9052130"          | A          | 资金账号                 |
| InstrumentID  | string | "ETHUSDT"          | I          | 标的代码                 |
| OffsetFlag    | string | "8"                | o          | 开平标志                 |
| Price         | float  | 1883.23            | P          | 成交价格                 |
| Volume        | int    | 50                 | V          | 成交数量                 |
| TradeTime     | int    | 1689698910         | TT         | 成交时间(待删除)         |
| MatchRole     | string | "1"                | m          | 成交角色                 |
| ClearCurrency | string | "USDT"             | CC         | 清算币种                 |
| Fee           | float  | 5.64969            | F          | 手续费                   |
| FeeCurrency   | string | "USDT"             | f          | 手续费币种               |
| CloseProfit   | float  | 39.34273504        | CP         | 平仓盈亏                 |
| Turnover      | float  | 9416.15            | T          | 成交金额                 |
| Leverage      | int    | 125                | l          | 杠杆倍数                 |
| InsertTime    | int    | 1689698910         | IT         | 成交时间                 |

### 响应示例

```json
{
  "action": "PushTrade",
  "result": [
    {
      "table": "Trade",
      "data": {
        "A": "36005550",
        "CC": "USDT",
        "D": "1",
        "F": 0.026451,
        "I": "BTCUSDT",
        "IT": 1690804738,
        "M": "36005550",
        "OS": "1000175061255804",
        "P": 29390,
        "T": 29.39,
        "TI": "1000168389225300",
        "TT": 1690804738,
        "V": 1,
        "c": 0,
        "f": "USDT",
        "l": 125,
        "m": "1",
        "o": "0"
      }
    }
  ]
}
```

# 账户明细

## 账户明细

### 响应参数

| 字段名          | 类型   | 示例值             | 简化字段名 | 字段描述                                                     |
| --------------- | ------ | ------------------ | ---------- | ------------------------------------------------------------ |
| AccountDetailID | string | "1000256882229328" | AD         | 资金明细号                                                   |
| MemberID        | string | "471114"           | M          | 成员代码                                                     |
| InstrumentID    | string | "BCHUSD"           | I          | 标的代码                                                     |
| AccountID       | string | "471114"           | A          | 资金账号                                                     |
| Currency        | string | "BCH"              | C          | 币种                                                         |
| Amount          | float  | -0.00009545        | Am         | 发生额                                                       |
| PreBalance      | float  | 5.83568833         | PB         | 上次静态权益                                                 |
| Balance         | float  | 5.83559288         | B          | 静态权益                                                     |
| Source          | string | "7"                | S          | 财务流水类型 `1`: "盈亏", `2`: "资金收支", `3`: "系统转入", `4`: "转出", `5`: "手续费", `7`: "资金费用", `8`: "结算", `a`: "强平", `g`: "预扣分润", `h`: "预扣分润退还", `i`: "带单分润", `j`: "体验金发放", `k`: "体验金回收" |
| Remark          | string | ""                 | R          | 备注                                                         |
| InsertTime      | int    | 1689696006         | IT         | 插入时间                                                     |
| RelatedID       | string | ""                 | r          | 关联 ID                                                      |

### 响应示例

```json
{
  "action": "PushAccountDetail",
  "result": [
    {
      "table": "AccountDetail",
      "data": {
        "A": "36005550",
        "AD": "1000167140823738",
        "Am": -0.026451,
        "B": 1998332.7691469,
        "C": "USDT",
        "I": "BTCUSDT",
        "IT": 1690804738,
        "M": "36005550",
        "PB": 1998332.7955979,
        "R": "",
        "S": "5",
        "r": "1000168389225300"
      }
    }
  ]
}
```

# 触发单通知

## 触发单通知

### 响应参数

| 字段名           | 类型   | 示例值             | 简化字段名 | 字段描述         |
| ---------------- | ------ | ------------------ | ---------- | ---------------- |
| MemberID         | string | "8853509"          | M          | 成员代码         |
| TradeUnitID      | string | "8853509"          | TU         | 交易单元代码     |
| AccountID        | string | "8853509"          | A          | 资金账号         |
| InstrumentID     | string | "BTCUSDT"          | I          | 标的代码         |
| OrderPriceType   | string | "0"                | OPT        | 报单价格类型     |
| Direction        | string | "1"                | D          | 买卖方向         |
| OffsetFlag       | string | "5"                | o          | 开平标志         |
| OrderType        | string | "0"                | OT         | 订单类型         |
| OrderSysID       | string | "1000466073338447" | OS         | 报单系统唯一代码 |
| Leverage         | int    | 125                | l          | 委托单杠杆倍数   |
| SLPrice          | int    | 31000              | SL         | 止损价           |
| SLTriggerPrice   | int    | 29000              | SLT        | 止损触发价       |
| TPPrice          | int    | 30010              | TP         | 止盈价           |
| TPTriggerPrice   | int    | 30000              | TPT        | 止盈触发价       |
| TriggerOrderType | string | "1"                | TO         | 触发的订单类型   |
| TriggerPriceType | string | "0"                | Tr         | 触发价类型       |
| TriggerStatus    | int    | "1"                | TS         | 触发报单状态     |
| InsertTime       | int    | 1689727248         | IT         | 插入时间         |
| UpdateTime       | int    | 1689727248         | U          | 更新时间         |

### 响应示例

```json
{
  "action": "PushTriggerOrder",
  "result": [
    {
      "table": "TriggerOrder",
      "data": {
        "A": "36005550",
        "D": "0",
        "I": "BTCUSDT",
        "IT": 1690786912,
        "M": "36005550",
        "O": "0",
        "OS": "1000175049516168",
        "OT": "0",
        "TO": "3",
        "TP": 20001,
        "TPT": 20000,
        "TS": "1",
        "TU": "36005550",
        "Tr": "0",
        "U": 1690786912,
        "l": 85,
        "o": "0"
      }
    }
  ]
}
```

# 强平订单订阅

## 接入地址

```
wss://stream.deepcoin.com/streamlet/trade/open/swap?platform=api&isStreamlet=true
```

| 参数名      | 类型   | 说明                                |
| ----------- | ------ | ----------------------------------- |
| platform    | string | 请求来源标识。                      |
| isStreamlet | bool   | 固定传 `true` 使用 Streamlet 通道。 |

### 请求头

| Header | 类型   | 说明    |
| ------ | ------ | ------- |
| uid    | string | 用户 ID |

## 订阅强平订单

```json
{
  "SendTopicAction": {
    "Action": "1",
    "LocalNo": 0,
    "TopicID": "30"
  }
}
```



| 字段    | 说明                                           |
| ------- | ---------------------------------------------- |
| Action  | 订阅行为：`1` 订阅，`0` 取消订阅。             |
| LocalNo | 本地自定义编号，可用不同编号同时订阅多个主题。 |
| TopicID | 主题 ID，`30` 表示强平订单主题。               |

## 心跳

发送 `ping`，服务端返回 `pong`。

## 响应示例

```json
{
  "a": "PFO",
  "c": "b",
  "r": [
    {
      "t": "Order",
      "d": {
        "I": "BTCUSDT",
        "D": "1",
        "P": 86339.9,
        "V": 11.0,
        "T": 1765866172
      }
    }
  ]
}
```



| 字段 | 说明                                           |
| ---- | ---------------------------------------------- |
| a    | 消息类型，`PFO` 为强平订单。                   |
| c    | 通道标识。                                     |
| r    | 载荷数组，包含字段 `t`（表名）与 `d`（数据）。 |
| t    | 数据表名称。                                   |
| I    | 交易对。                                       |
| D    | 方向：`0` 买，`1` 卖。                         |
| P    | 强平价。                                       |
| V    | 成交量。                                       |
| T    | 成交时间（Unix 秒）。                          |

# WebSocket公有频道

## 主网

```
合约: wss://stream.deepcoin.com/streamlet/trade/public/swap?platform=api
现货: wss://stream.deepcoin.com/streamlet/trade/public/spot?platform=api
```

## 访问方式

```text
# 发送心跳
request:
ping
response:
pong
```



### 请求参数

| parameter   | required | type   | description    | remark                                                       |
| ----------- | -------- | ------ | -------------- | ------------------------------------------------------------ |
| Action      | yes      | string | 订阅操作       | 0:全部退订;1:订阅;2:退订;                                    |
| FilterValue | yes      | string | 过滤值         | 格式:$ExchangeID_$InstrumentID_$Period Period 取值范围[1m:1 分钟;5m:5 分钟;15m:15 分钟;30m:30 分钟;1h:1 小时;4h:4 小时;12h:12 小时;1d:一天;1w:一个星期;1o:一个月;1y:一年;] 现货使用 `BASE/QUOTE`（如 `DeepCoin_BTC/USDT`），合约不加斜杠（如 `DeepCoin_BTCUSDT`）。 |
| LocalNo     | yes      | int    | 本地唯一标识号 | 大于 0, 字符串比较, 自定义,一次会话中不能重复                |
| ResumeNo    | yes      | int    | 续传号         | 0:从头开始;-1:从服务端最新位置续传;                          |
| TopicID     | yes      | string | 订阅主题标识   | 2:成交明细                                                   |

# 最新行情

## 最新行情

### 请求示例

#### 现货请求

```json
{
  "SendTopicAction": {
    "Action": "1",
    "FilterValue": "DeepCoin_BCH/USDT",
    "LocalNo": 9,
    "ResumeNo": -2,
    "TopicID": "7"
  }
}
```



#### 合约请求

```json
{
  "SendTopicAction": {
    "Action": "1",
    "FilterValue": "DeepCoin_BCHUSDT",
    "LocalNo": 9,
    "ResumeNo": -2,
    "TopicID": "7"
  }
}
```



### 响应参数

| 字段名 | 类型   | 示例值           | 字段描述         |
| ------ | ------ | ---------------- | ---------------- |
| I      | string | "BTCUSDT"        | 标的代码         |
| U      | int    | 1757642301089    | 最后修改毫秒     |
| PF     | int    | 1756690200       | 持仓费时间       |
| C      | double | 173183.6         | 最高限价         |
| F      | double | 57727.9          | 最低限价         |
| D      | double | 115455.77        | 基础标的价格     |
| M      | double | 115473.7         | 标记价格         |
| H      | double | 116346           | 当日最高价       |
| L      | double | 114132.8         | 当日最低价       |
| N      | double | 115482.9         | 最新价           |
| V      | double | 7688046          | 当日成交数量     |
| T      | double | 885654450.392686 | 当日成交金额     |
| O      | double | 114206.7         | 当日开盘价       |
| PF     | double | 0.0005251816     | 上次持仓费按比例 |

### 响应示例

```json
{
    "a": "PO",
    "m": "Success",
    "tt": 1757642301185,
    "mt": 1757642301185,
    "r": [
        {
            "d": {
                "I": "BTCUSDT",
                "U": 1757642301089,
                "PF": 1756690200,
                "E": 0.0005251816,
                "O": 114206.7,
                "H": 116346,
                "L": 114132.8,
                "V": 7688046,
                "T": 885654450.392686,
                "N": 115482.9,
                "M": 115473.7,
                "D": 115455.77,
                "V2": 19978848,
                "T2": 2288286517.724497,
                "F": 57727.9,
                "C": 173183.6,
                "BP1": 115482.8,
                "AP1": 115482.9
            }
        }
    ]
}
```

# 最近成交

## 最近成交

### 请求示例

#### 现货请求

```json
{
  "SendTopicAction": {
    "Action": "1",
    "FilterValue": "DeepCoin_BTC/USDT",
    "LocalNo": 9,
    "ResumeNo": -2,
    "TopicID": "2"
  }
}
```



#### 合约请求

```json
{
  "SendTopicAction": {
    "Action": "1",
    "FilterValue": "DeepCoin_BTCUSDT",
    "LocalNo": 9,
    "ResumeNo": -2,
    "TopicID": "2"
  }
}
```



### 响应参数

| 字段名  | 类型   | 示例值             | 字段描述    |
| ------- | ------ | ------------------ | ----------- |
| TradeID | string | "1000170423277947" | 成交唯一 id |
| I       | string | "ETHUSDT"          | 交易对      |
| D       | string | "1"                | 方向        |
| P       | int    | 4519.91            | 价格        |
| V       | float  | 4                  | 数量        |
| T       | int    | 1757640595         | 成交时间    |

### 响应示例

```json
{
    "a": "PMT",
    "b": 0,
    "tt": 1757640595167,
    "mt": 1757640595167,
    "r": [
        {
            "d": {
                "TradeID": "1000170423277947",
                "I": "ETHUSDT",
                "D": "1",
                "P": 4519.91,
                "V": 4,
                "T": 1757640595
            }
        }
    ]
}
```

# K线（仅支持一分钟）

## K 线（当前仅支持一分钟）

ResumeNo：-1 从最新开始推，-30 表示推送历史的 30 条

### 请求示例

#### 现货请求

```json
{
  "SendTopicAction": {
    "Action": "1",
    "FilterValue": "DeepCoin_BTC/USDT_1m",
    "LocalNo": 6,
    "ResumeNo": -1,
    "TopicID": "11"
  }
}
```



#### 合约请求

```json
{
  "SendTopicAction": {
    "Action": "1",
    "FilterValue": "DeepCoin_BTCUSDT_1m",
    "LocalNo": 6,
    "ResumeNo": -1,
    "TopicID": "11"
  }
}
```



### 响应参数

| 字段名 | 类型   | 示例值     | 字段描述 |
| ------ | ------ | ---------- | -------- |
| I      | string | "BTCUSDT"  | 交易对   |
| P      | string | 1m         | 间隔     |
| B      | int    | 1691992620 | 开始时间 |
| O      | float  | 29437.2    | 开仓价格 |
| C      | float  | 29437.2    | 收盘价格 |
| H      | float  | 29437.2    | 最高价   |
| L      | float  | 29437.2    | 最低价   |
| V      | float  | 2554       | 数量     |
| M      | float  | 75182.5694 | 成交金额 |

### 响应示例

```json
{
    "a": "PK",
    "tt": 1757640455199,
    "mt": 1757640455199,
    "r": [
        {
            "d": {
                "I": "BTCUSDT",
                "P": "1m",
                "B": 1757640420,
                "O": 115819,
                "C": 115788.4,
                "H": 115819,
                "L": 115787.6,
                "V": 4989,
                "M": 577697.5531
            },
            "t": "LK"
        }
    ]
}
```

# 5 档增量行情

## 25 档增量行情

200ms 推送一次

### 请求示例

#### 现货请求

```json
{
  "SendTopicAction": {
    "Action": "1",
    "FilterValue": "DeepCoin_BTC/USDT_0.1",
    "LocalNo": 6,
    "ResumeNo": -1,
    "TopicID": "25"
  }
}
```



#### 合约请求

```json
{
  "SendTopicAction": {
    "Action": "1",
    "FilterValue": "DeepCoin_BTCUSDT_0.1",
    "LocalNo": 6,
    "ResumeNo": -1,
    "TopicID": "25"
  }
}
```



### 响应参数

| 字段名 | 类型   | 示例值    | 字段描述 |
| ------ | ------ | --------- | -------- |
| I      | string | "BTCUSDT" | 交易对   |
| D      | string | "1"       | 方向     |
| P      | int    | 29417.3   | 价格     |
| V      | int    | 6432      | 数量     |

### 响应示例

```json
{
  "a": "PMO",
  "t": "i",
  "r": [
    {
      "d": {
              "I": "BTCUSDT",
              "D": "0",
              "P": 115970.7,
              "V": 13285.0
          }
      },
      {
          "d": {
              "I": "BTCUSDT",
              "D": "0",
              "P": 115970.6,
              "V": 1272.0
          }
      }
   ]
}
```