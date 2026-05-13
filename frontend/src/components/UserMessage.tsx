export function UserMessage({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-2xl bg-slate-900 text-white px-5 py-3 rounded-2xl rounded-tr-none text-sm font-medium shadow-sm whitespace-pre-wrap">
        {text}
      </div>
    </div>
  );
}
