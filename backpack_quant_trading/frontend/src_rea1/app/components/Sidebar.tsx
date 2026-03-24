import React from 'react';

export function Sidebar() {
  return (
    <aside className="w-60 bg-white border-r border-gray-200 flex flex-col">
      {/* Logo */}
      <div className="p-6 border-b border-gray-200">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-blue-600 rounded-lg flex items-center justify-center text-white">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-6 h-6">
              <path d="M12 2L2 7l10 5 10-5-10-5z"/>
              <path d="M2 17l10 5 10-5"/>
              <path d="M2 12l10 5 10-5"/>
            </svg>
          </div>
          <div>
            <div className="text-lg font-bold text-blue-600">沐龙量化</div>
            <div className="text-xs text-gray-500">Admin · v1.0</div>
          </div>
        </div>
      </div>

      {/* Menu */}
      <nav className="flex-1 p-3 overflow-y-auto">
        {menuItems.map((item, index) => (
          <button
            key={index}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-left mb-1 ${
              item.active
                ? 'bg-blue-50 text-blue-600'
                : 'text-gray-700 hover:bg-gray-50'
            }`}
          >
            {item.icon}
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-gray-200">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center text-blue-600 font-semibold text-xs">
            ML
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-1">
              <span className="w-2 h-2 bg-green-500 rounded-full"></span>
              <span className="text-xs text-gray-600">运行正常</span>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}

const menuItems = [
  { label: '实盘交易', active: false, icon: <span>⚡</span> },
  { label: '数据大屏', active: false, icon: <span>📊</span> },
  { label: 'AI 实验室', active: false, icon: <span>🧪</span> },
  { label: '合约网格', active: false, icon: <span>📐</span> },
  { label: '币种监视', active: false, icon: <span>🔔</span> },
  { label: 'A股 AI 选股', active: false, icon: <span>📈</span> },
  { label: '量化策略矩阵', active: true, icon: <span>📋</span> },
  { label: 'OKX AI 交易', active: false, icon: <span>🔄</span> },
  { label: 'OKX 操作台', active: false, icon: <span>▶️</span> }
];
