type SearchingLabelProps = {
  text: string;
};

export default function SearchingLabel({ text }: SearchingLabelProps) {
  return (
    <span className="searching-label">
      {text}
      <span className="searching-dots" aria-hidden="true">
        <span>.</span>
        <span>.</span>
        <span>.</span>
      </span>
    </span>
  );
}
