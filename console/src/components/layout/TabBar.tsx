import { NavLink } from 'react-router-dom';
import { useDeviceStore } from '../../stores/deviceStore';

const ICON_MAP: Record<string, string> = {
  cpu: '🔌', 'arrow-left-right': '📡', activity: '📶',
  bluetooth: '📶', network: '🌐',
};

export function TabBar() {
  const config = useDeviceStore((s) => s.hardwareConfig);
  const groups = (config?.feature_groups || []).filter((g) => g.enabled);

  const tabs = [
    { to: '/', label: '芯片视图', icon: '💻' },
    ...groups.map((g) => ({
      to: `/commands?tab=${g.id}`,
      label: g.label,
      icon: ICON_MAP[g.id] || '⚡',
    })),
    { to: '/custom-commands', label: '自定义指令', icon: '📋' },
  ];

  return (
    <nav className="flex border-t border-gray-700 bg-gray-900">
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          className={({ isActive }) =>
            `flex-1 text-center py-2 text-xs ${isActive ? 'text-blue-400 border-t-2 border-blue-400 bg-gray-800' : 'text-gray-500 hover:text-gray-300'}`
          }
        >
          <div className="text-base">{tab.icon}</div>
          <div className="mt-0.5">{tab.label}</div>
        </NavLink>
      ))}
    </nav>
  );
}
