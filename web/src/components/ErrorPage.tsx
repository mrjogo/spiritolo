import { Link } from 'react-router-dom';

type Props = { title: string; message: string };

export function ErrorPage({ title, message }: Props) {
  return (
    <div className="error-page">
      <h1>{title}</h1>
      <p>{message}</p>
      <p>
        <Link to="/">← Back to recipes</Link>
      </p>
    </div>
  );
}
