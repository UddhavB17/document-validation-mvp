export function TextField({
  name,
  label,
  required = false,
  type = "text",
}: {
  name: string;
  label: string;
  required?: boolean;
  type?: string;
}) {
  return (
    <label className="block text-sm font-medium">
      <span className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">{label}</span>
      <input
        className="block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs text-sm font-medium"
        name={name}
        type={type}
        required={required}
      />
    </label>
  );
}

export function SelectField({ name, label, options }: { name: string; label: string; options: string[] }) {
  return (
    <label className="block text-sm font-medium">
      <span className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">{label}</span>
      <select
        className="block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs cursor-pointer text-sm font-medium"
        name={name}
      >
        {options.map((option) => (
          <option key={option} className="bg-white text-[#16202E]">
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}
