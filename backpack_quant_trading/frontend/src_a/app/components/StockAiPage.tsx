import { useEffect, useState } from 'react';
import {
  getBoards,
  getIndustries,
  screenStocks,
  analyzeStocksWithDaily,
  analyzeSingleStock,
  getDailyPredict,
  trainModel,
  refreshKlineCache,
} from '../api/stockAi';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { MultiSelect } from './ui/multi-select';
import {
  TrendingUp,
  TrendingDown,
  BarChart3,
  Sparkles,
  Filter,
  RefreshCw,
  Play,
  Database,
  Search,
  AlertCircle,
  ChevronUp,
  ChevronDown,
  Activity,
  Target,
  Zap,
  Brain,
  LineChart,
} from 'lucide-react';

const DEFAULT_BOARDS = [
  { value: '主板', label: '主板（沪市+深市）' },
  { value: '创业板', label: '创业板' },
  { value: '科创板', label: '科创板' },
  { value: '北交所', label: '北交所' },
];

const DEFAULT_INDUSTRIES = [
  { value: '化学原料', label: '化学原料' },
  { value: '贵金属', label: '贵金属' },
  { value: '电力', label: '电力' },
  { value: '银行', label: '银行' },
  { value: '半导体', label: '半导体' },
];

const scoreClass = (score: number | null) => {
  if (score == null) return 'text-gray-500';
  if (score >= 70) return 'text-green-600 font-bold';
  if (score >= 50) return 'text-blue-600 font-semibold';
  return 'text-gray-600';
};

const pctClass = (pct: number | null) => {
  if (pct == null) return 'text-gray-500';
  if (pct > 0) return 'text-red-600 font-semibold';
  if (pct < 0) return 'text-green-600 font-semibold';
  return 'text-gray-600';
};

const probaClass = (proba: number | null) => {
  if (proba == null) return 'text-gray-500';
  if (proba >= 0.6) return 'text-green-600 font-bold';
  if (proba >= 0.5) return 'text-blue-600 font-semibold';
  return 'text-gray-600';
};

export function StockAiPage() {
  const [boardOptions, setBoardOptions] = useState([...DEFAULT_BOARDS]);
  const [industryOptions, setIndustryOptions] = useState([...DEFAULT_INDUSTRIES]);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  const [aiAnalysis, setAiAnalysis] = useState('');
  const [screenError, setScreenError] = useState('');
  const [screenDoneOnce, setScreenDoneOnce] = useState(false);
  const [candidatesCount, setCandidatesCount] = useState(0);
  const [fromFullMarket, setFromFullMarket] = useState(false);
  const [dailyPredictList, setDailyPredictList] = useState<any[]>([]);
  const [dailyPredictLoading, setDailyPredictLoading] = useState(false);
  const [dailyPredictError, setDailyPredictError] = useState('');
  const [dailyPredictDate, setDailyPredictDate] = useState('');
  const [trainLoading, setTrainLoading] = useState(false);
  const [trainMessage, setTrainMessage] = useState('');
  const [trainSuccess, setTrainSuccess] = useState(false);
  const [cacheRefreshing, setCacheRefreshing] = useState(false);
  const [singleStockCode, setSingleStockCode] = useState('');
  const [singleAnalyzing, setSingleAnalyzing] = useState(false);
  const [singleAnalysis, setSingleAnalysis] = useState('');
  const [form, setForm] = useState({
    boards: [] as string[],
    industries: [] as string[],
    top_n: 30,
    min_score: 0,
    lookback_days: 120,
  });

  const usedFilters = [
    ...(form.boards?.length ? ['板块: ' + form.boards.join(', ')] : []),
    ...(form.industries?.length ? ['行业: ' + form.industries.join(', ')] : []),
  ].join('；');

  const loadOptions = async () => {
    try {
      const [b, i]: any = await Promise.all([getBoards(), getIndustries()]);
      const boards = b?.options?.length ? b.options : DEFAULT_BOARDS;
      const industries = i?.options?.length ? i.options : DEFAULT_INDUSTRIES;
      setBoardOptions(boards);
      setIndustryOptions(industries);
    } catch (_) {
      setBoardOptions([...DEFAULT_BOARDS]);
      setIndustryOptions([...DEFAULT_INDUSTRIES]);
    }
  };

  useEffect(() => {
    loadOptions();
  }, []);

  const runRefreshCache = async () => {
    setCacheRefreshing(true);
    try {
      const res: any = await refreshKlineCache();
      if (res?.ok) {
        alert(
          res.message || `缓存已更新，新增 ${res.rows_added || 0} 条，最新日期 ${res.max_date || '-'}`
        );
      } else {
        alert(res?.message || '刷新失败');
      }
    } catch (e: any) {
      alert(e?.response?.data?.detail ?? e?.message ?? '请求失败');
    } finally {
      setCacheRefreshing(false);
    }
  };

  const runTrain = async () => {
    setTrainLoading(true);
    setTrainMessage('');
    setTrainSuccess(false);
    try {
      const res: any = await trainModel({
        stock_codes: ['000001', '000002', '600000', '600519', '000858', '601318', '000333', '600036'],
        forward_days: 5,
        lookback_days: 500,
      });
      if (res.ok) {
        setTrainSuccess(true);
        setTrainMessage(
          `训练完成。模型已保存，样本数 ${res.n_samples}，股票数 ${res.n_stocks}。可点击「获取今日预测」。`
        );
        alert('模型训练完成');
      } else {
        const errMsg = res.error || '训练失败';
        setTrainMessage(errMsg);
        alert(errMsg);
      }
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || '训练请求失败，请检查后端与网络';
      setTrainMessage(msg);
      alert(msg);
    } finally {
      setTrainLoading(false);
    }
  };

  const fetchDailyPredict = async (forceRefresh: boolean, screenResults: any[] | null) => {
    setDailyPredictLoading(true);
    setDailyPredictError('');
    const useScreenPool = Array.isArray(screenResults) && screenResults.length > 0;
    try {
      const payload: any = { force_refresh: !!forceRefresh || !!useScreenPool, top_n: 20 };
      if (useScreenPool) payload.stock_codes = screenResults.map((r) => r.code).filter(Boolean);
      const res: any = await getDailyPredict(payload);
      setDailyPredictList(res.list || []);
      setDailyPredictDate(res.date || '');
      if (res.error) setDailyPredictError(res.error);
      else
        alert(
          useScreenPool
            ? `已对选股结果预测，共 ${(res.list || []).length} 只`
            : `今日预测已更新，共 ${(res.list || []).length} 只`
        );
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || '获取每日预测失败';
      setDailyPredictError(msg);
      alert(msg);
    } finally {
      setDailyPredictLoading(false);
    }
  };

  const resetForm = () => {
    setForm({
      boards: [],
      industries: [],
      top_n: 30,
      min_score: 0,
      lookback_days: 120,
    });
  };

  const runScreen = async () => {
    setLoading(true);
    setResults([]);
    setScreenError('');
    setCandidatesCount(0);
    setFromFullMarket(false);
    try {
      const res: any = await screenStocks({
        boards: form.boards,
        industries: form.industries,
        top_n: form.top_n,
        min_score: form.min_score,
        lookback_days: form.lookback_days,
      });
      setResults(res.list || []);
      setScreenError(res.error || '');
      setScreenDoneOnce(true);
      setCandidatesCount(res.candidates_count ?? 0);
      setFromFullMarket(res.from_full_market ?? false);
      if (res.error) alert(res.error);
      else {
        const n = res.candidates_count ?? 0;
        const len = (res.list || []).length;
        const fromFull = res.from_full_market ?? false;
        alert(
          n > 0
            ? fromFull
              ? `全市场 ${n} 只中得分前 ${len} 只`
              : `共 ${len} 只（从 ${n} 只中选出）`
            : len
              ? `选股完成，共 ${len} 只`
              : '选股完成，共 0 只。可调低「最低得分」或先点「刷新 K 线缓存」再选股'
        );
      }
    } catch (e: any) {
      const msg = e?.response?.data?.detail ?? e?.response?.data?.error ?? e?.message;
      const status = e?.response?.status;
      const errStr = status === 401 ? '请先登录' : msg ? (typeof msg === 'string' ? msg : String(msg)) : '选股请求失败，请检查网络或后端是否启动';
      setScreenError(errStr);
      alert(errStr);
    } finally {
      setLoading(false);
    }
    setAiAnalysis('');
  };

  const runAnalyze = async () => {
    if (!results.length) {
      alert('请先执行选股');
      return;
    }
    setAnalyzing(true);
    setAiAnalysis('');
    try {
      const res: any = await analyzeStocksWithDaily(results);
      setAiAnalysis(res.analysis || '');
      if (res.analysis) alert('AI 解读完成');
    } catch (e: any) {
      const msg = e?.response?.data?.detail ?? e?.message ?? 'AI 解读失败';
      alert(typeof msg === 'string' ? msg : 'AI 解读失败');
    } finally {
      setAnalyzing(false);
    }
  };

  const runSingleAnalyze = async () => {
    const code = (singleStockCode || '').trim();
    if (!code) {
      alert('请输入股票代码');
      return;
    }
    setSingleAnalyzing(true);
    setSingleAnalysis('');
    try {
      const res: any = await analyzeSingleStock(code);
      setSingleAnalysis(res.analysis || '');
      if (res.analysis) alert('股票分析完成');
    } catch (e: any) {
      const msg = e?.response?.data?.detail ?? e?.message ?? '股票分析请求失败';
      setSingleAnalysis(msg);
      alert(typeof msg === 'string' ? msg : '股票分析失败');
    } finally {
      setSingleAnalyzing(false);
    }
  };

  return (
    <div className="p-6 space-y-6 bg-gray-50">
      {/* Header */}
      <div>
        <div className="flex items-center space-x-3">
          <h1 className="text-2xl font-bold text-gray-900">A股 AI 选股</h1>
          <Badge className="bg-purple-100 text-purple-700 border-0">
            <Sparkles className="w-3 h-3 mr-1" />
            智能分析
          </Badge>
        </div>
        <p className="text-sm text-gray-500 mt-1">
          按板块、行业筛选，结合 MACD / RSI / KDJ / 量比等指标综合打分，偏多标的供短期（3～5 日）关注参考
        </p>
      </div>

      {/* Filter Card */}
      <Card className="border border-gray-200 shadow-sm">
        <CardHeader className="border-b border-gray-100 bg-white">
          <CardTitle className="flex items-center space-x-2 text-base font-semibold">
            <Filter className="w-4 h-4 text-blue-600" />
            <span>筛选条件</span>
            {usedFilters && (
              <Badge variant="outline" className="ml-2 text-xs">
                {usedFilters}
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-6 bg-white space-y-5">
          <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
            <div className="flex items-start space-x-2">
              <AlertCircle className="w-4 h-4 text-blue-600 mt-0.5" />
              <p className="text-sm text-blue-800">
                选股会逐只拉取日线数据（来源：腾讯/新浪/东方财富），
                <strong>接口较慢或限流时等待会较长</strong>。可把「返回数量」或「回溯天数」调小以加快。
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-5">
            <div className="space-y-2">
              <Label className="text-sm font-medium">板块</Label>
              <MultiSelect
                options={boardOptions.map((b) => b.value)}
                selected={form.boards}
                onChange={(boards) => setForm((prev) => ({ ...prev, boards }))}
                placeholder="选择板块（不选则全部）"
                searchPlaceholder="搜索板块..."
                emptyText="未找到板块"
              />
            </div>

            <div className="space-y-2">
              <Label className="text-sm font-medium">行业</Label>
              <MultiSelect
                options={industryOptions.map((i) => i.value)}
                selected={form.industries}
                onChange={(industries) => setForm((prev) => ({ ...prev, industries }))}
                placeholder="选择行业（不选则全部）"
                searchPlaceholder="搜索行业..."
                emptyText="未找到行业"
              />
            </div>

            <div className="space-y-2">
              <Label className="text-xs text-gray-600">返回数量</Label>
              <Input
                type="number"
                min={0}
                max={100}
                step={5}
                value={form.top_n}
                onChange={(e) => setForm((prev) => ({ ...prev, top_n: Number(e.target.value) }))}
                className="h-10"
              />
            </div>

            <div className="space-y-2">
              <Label className="text-xs text-gray-600">最低得分</Label>
              <Input
                type="number"
                min={0}
                max={100}
                step={5}
                value={form.min_score}
                onChange={(e) => setForm((prev) => ({ ...prev, min_score: Number(e.target.value) }))}
                className="h-10"
              />
            </div>

            <div className="space-y-2">
              <Label className="text-xs text-gray-600">回溯天数</Label>
              <Input
                type="number"
                min={30}
                max={250}
                step={30}
                value={form.lookback_days}
                onChange={(e) => setForm((prev) => ({ ...prev, lookback_days: Number(e.target.value) }))}
                className="h-10"
              />
            </div>
          </div>

          <div className="flex items-center space-x-3 pt-2">
            <Button onClick={runScreen} disabled={loading} className="bg-blue-600 hover:bg-blue-700">
              <Search className="w-4 h-4 mr-2" />
              {loading ? '选股中...' : '开始选股'}
            </Button>
            <Button variant="outline" onClick={resetForm}>
              <RefreshCw className="w-4 h-4 mr-2" />
              重置
            </Button>
            <Button
              variant="outline"
              onClick={runRefreshCache}
              disabled={cacheRefreshing}
              className="border-orange-200 text-orange-600 hover:bg-orange-50"
            >
              <Database className="w-4 h-4 mr-2" />
              {cacheRefreshing ? '刷新中...' : '刷新 K 线缓存'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Single Stock Analysis */}
      <Card className="border border-purple-200 shadow-sm bg-gradient-to-br from-purple-50 to-white">
        <CardHeader className="border-b border-purple-100">
          <CardTitle className="flex items-center space-x-2 text-base font-semibold">
            <Brain className="w-4 h-4 text-purple-600" />
            <span>单股分析</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-6 bg-white space-y-4">
          <p className="text-sm text-gray-600">
            输入 6 位 A 股代码（如 000001、600519），从数据源拉取日 K 线后由 DeepSeek 进行技术分析
          </p>
          <div className="flex items-center space-x-3">
            <Input
              value={singleStockCode}
              onChange={(e) => setSingleStockCode(e.target.value.slice(0, 6))}
              placeholder="输入股票代码，如 000001"
              maxLength={6}
              className="h-11 max-w-xs"
              onKeyDown={(e) => e.key === 'Enter' && runSingleAnalyze()}
            />
            <Button
              onClick={runSingleAnalyze}
              disabled={singleAnalyzing}
              className="bg-purple-600 hover:bg-purple-700"
            >
              <Sparkles className="w-4 h-4 mr-2" />
              {singleAnalyzing ? '分析中...' : 'DeepSeek 分析'}
            </Button>
          </div>
          {singleAnalysis && (
            <div className="p-4 bg-gray-50 border border-gray-200 rounded-lg">
              <p className="text-sm font-semibold text-gray-700 mb-2">DeepSeek 分析结果</p>
              <pre className="text-sm text-gray-800 whitespace-pre-wrap font-mono">{singleAnalysis}</pre>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Daily Prediction */}
      <Card className="border border-green-200 shadow-sm">
        <CardHeader className="border-b border-green-100 bg-white">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center space-x-2 text-base font-semibold">
              <TrendingUp className="w-4 h-4 text-green-600" />
              <span>每日预测（未来 3~5 日看涨）</span>
            </CardTitle>
            <div className="flex items-center space-x-2">
              <Button
                size="sm"
                onClick={() => fetchDailyPredict(false, null)}
                disabled={dailyPredictLoading}
                className="bg-green-600 hover:bg-green-700"
              >
                <Play className="w-3 h-3 mr-1" />
                获取今日预测
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => fetchDailyPredict(true, null)}
                disabled={dailyPredictLoading}
              >
                <RefreshCw className="w-3 h-3 mr-1" />
                强制刷新
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => fetchDailyPredict(true, results)}
                disabled={dailyPredictLoading || !results.length}
                className="border-blue-200 text-blue-600 hover:bg-blue-50"
              >
                <Target className="w-3 h-3 mr-1" />
                对选股结果预测
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-6 bg-white">
          <p className="text-sm text-gray-600 mb-4">
            请先完成「模型训练」后再使用。「获取今日预测」从全市场主板取前 80 只算看涨概率排序；「对选股结果预测」用当前选股结果作为股票池算看涨概率。
          </p>
          {dailyPredictError && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              {dailyPredictError}
            </div>
          )}
          {!dailyPredictError && dailyPredictList.length === 0 && !dailyPredictLoading && (
            <div className="text-center py-8 text-gray-500">点击「获取今日预测」拉取当日看涨排序</div>
          )}
          {dailyPredictList.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">序号</th>
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">代码</th>
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">名称</th>
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">看涨概率</th>
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">最新价</th>
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">更新日期</th>
                  </tr>
                </thead>
                <tbody>
                  {dailyPredictList.map((row, i) => (
                    <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="py-3 px-4">{i + 1}</td>
                      <td className="py-3 px-4 font-mono">{row.code}</td>
                      <td className="py-3 px-4">{row.name}</td>
                      <td className={`py-3 px-4 ${probaClass(row.proba_up)}`}>
                        {row.proba_up != null ? (row.proba_up * 100).toFixed(1) : 0}%
                      </td>
                      <td className="py-3 px-4">{row.close != null ? row.close.toFixed(2) : '-'}</td>
                      <td className="py-3 px-4 text-gray-500">{dailyPredictDate || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Results */}
      <Card className="border border-gray-200 shadow-sm">
        <CardHeader className="border-b border-gray-100 bg-white">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <CardTitle className="flex items-center space-x-2 text-base font-semibold">
                <BarChart3 className="w-4 h-4 text-blue-600" />
                <span>选股结果</span>
              </CardTitle>
              <Badge className="bg-blue-600 text-white border-0">{results.length}</Badge>
              {candidatesCount > 0 && (
                <Badge variant="outline" className="text-xs">
                  {fromFullMarket
                    ? `全市场 ${candidatesCount} 只中得分前 ${results.length} 只`
                    : `从 ${candidatesCount} 只中选出`}
                </Badge>
              )}
            </div>
            {results.length > 0 && (
              <Button
                size="sm"
                onClick={runAnalyze}
                disabled={analyzing}
                className="bg-purple-600 hover:bg-purple-700"
              >
                <Sparkles className="w-3 h-3 mr-1" />
                {analyzing ? '解读中...' : 'DeepSeek AI 解读'}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="p-6 bg-white">
          {screenError && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 mb-4">
              {screenError}
            </div>
          )}
          {aiAnalysis && (
            <div className="p-4 bg-purple-50 border border-purple-200 rounded-lg mb-4">
              <p className="text-sm font-semibold text-purple-700 mb-2">DeepSeek 解读与建议</p>
              <pre className="text-sm text-gray-800 whitespace-pre-wrap font-mono">{aiAnalysis}</pre>
            </div>
          )}
          {results.length === 0 && !loading && !screenError && (
            <div className="text-center py-12">
              <div className="w-16 h-16 bg-blue-50 rounded-xl flex items-center justify-center mx-auto mb-4">
                <LineChart className="w-8 h-8 text-blue-400" />
              </div>
              <h3 className="text-base font-semibold text-gray-900 mb-2">
                {screenDoneOnce ? '未筛出符合条件的股票' : '等待选股'}
              </h3>
              <p className="text-sm text-gray-500">
                {screenDoneOnce
                  ? '可调低「最低得分」或更换板块/行业后重试'
                  : '请选择条件后点击「开始选股」，或保持默认全部进行选股'}
              </p>
            </div>
          )}
          {results.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">序号</th>
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">代码</th>
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">名称</th>
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">市场</th>
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">综合得分</th>
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">最新价</th>
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">涨跌幅</th>
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">MACD</th>
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">RSI</th>
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">KDJ(J)</th>
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">量比</th>
                    <th className="text-left py-3 px-4 font-semibold text-gray-700">说明</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((row, i) => (
                    <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="py-3 px-4">{i + 1}</td>
                      <td className="py-3 px-4 font-mono">{row.code}</td>
                      <td className="py-3 px-4 font-semibold">{row.name}</td>
                      <td className="py-3 px-4 text-gray-600">{row.market}</td>
                      <td className={`py-3 px-4 ${scoreClass(row.score)}`}>
                        {row.score != null ? row.score.toFixed(1) : '-'}
                      </td>
                      <td className="py-3 px-4">{row.close != null ? row.close.toFixed(2) : '-'}</td>
                      <td className={`py-3 px-4 ${pctClass(row.pct_chg)}`}>
                        {row.pct_chg != null ? (
                          <>
                            {row.pct_chg > 0 ? <ChevronUp className="w-4 h-4 inline" /> : <ChevronDown className="w-4 h-4 inline" />}
                            {row.pct_chg.toFixed(2)}%
                          </>
                        ) : (
                          '-'
                        )}
                      </td>
                      <td className="py-3 px-4">
                        {row.details?.macd_hist != null
                          ? (row.details.macd_hist >= 0 ? '🔴 ' : '🟢 ') +
                            Math.abs(row.details.macd_hist).toFixed(2)
                          : '-'}
                      </td>
                      <td className="py-3 px-4">{row.details?.rsi != null ? row.details.rsi.toFixed(0) : '-'}</td>
                      <td className="py-3 px-4">{row.details?.kdj_j != null ? row.details.kdj_j.toFixed(0) : '-'}</td>
                      <td className="py-3 px-4">
                        {row.details?.volume_ratio != null ? row.details.volume_ratio.toFixed(2) : '-'}
                      </td>
                      <td className="py-3 px-4 text-gray-600">{row.description || '量价/均线等已计入综合得分'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
