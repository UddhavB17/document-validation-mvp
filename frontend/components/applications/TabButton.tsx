export function TabButton({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2.5 text-sm font-semibold transition-all rounded-lg select-none ${
        active
          ? "bg-white text-blue-700 shadow-sm border border-slate-200/50"
          : "text-slate-500 hover:text-slate-800 hover:bg-slate-200/50"
      }`}
    >
      {children}
    </button>
  );
}
