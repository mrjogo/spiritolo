import { Link } from 'react-router-dom';
import type { RecipeIngredientRow } from '../../types';

interface Props {
  rawLines: string[];
  parsedByPosition: Map<number, RecipeIngredientRow> | null;
}

export function StructuredIngredients({ rawLines, parsedByPosition }: Props) {
  const isAdmin = parsedByPosition !== null;

  return (
    <ul className={isAdmin ? 'recipe-detail__ingredients recipe-detail__ingredients--admin' : 'recipe-detail__ingredients'}>
      {rawLines.map((raw, i) => (
        <li key={i}>
          <span className="recipe-detail__ingredients-raw">{raw}</span>
          {isAdmin && <ParsedCard row={parsedByPosition!.get(i) ?? null} />}
        </li>
      ))}
    </ul>
  );
}

function ParsedCard({ row }: { row: RecipeIngredientRow | null }) {
  if (row === null) {
    return (
      <div className="recipe-detail__parsed-card recipe-detail__parsed-card--missing">
        <em>not parsed</em>
      </div>
    );
  }
  if (row.parse_status === 'unparseable') {
    return (
      <div className="recipe-detail__parsed-card recipe-detail__parsed-card--unparseable">
        <em>unparseable</em>
      </div>
    );
  }
  return (
    <div className="recipe-detail__parsed-card">
      <span className="recipe-detail__parsed-id">#{row.id}</span>
      <span className="recipe-detail__parsed-amount">{formatAmount(row)}</span>
      <span className="recipe-detail__parsed-name">
        {row.taxonomy_nodes != null ? (
          <Link to={`/taxonomy?node=${row.taxonomy_nodes.slug}`}>
            {row.taxonomy_nodes.display_name}
          </Link>
        ) : (
          row.name ?? ''
        )}
      </span>
      {row.modifier && (
        <span className="recipe-detail__parsed-modifier">{row.modifier}</span>
      )}
      {row.role && (
        <span className={`recipe-detail__parsed-role recipe-detail__parsed-role--${row.role}`}>
          {row.role}
        </span>
      )}
    </div>
  );
}

function formatAmount(row: RecipeIngredientRow): string {
  if (row.amount == null) return '';
  const num = row.amount_max != null ? `${row.amount}–${row.amount_max}` : String(row.amount);
  return row.unit ? `${num} ${row.unit}` : num;
}
