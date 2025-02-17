"""Swap the underlying indices of an OpenSearch alias"""

import argparse

from opensearch_indexing.opensearch_manager import OpenSearchManager


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('alias', type=str, help='Alias to modify')
    parser.add_argument('remove', type=str, help='Old index to remove from the alias')
    parser.add_argument('add', type=str, help='New index to add to the alias')
    parser.add_argument('--delete', action='store_true', help='Delete the old index after removal')
    args = parser.parse_args()
    opensearch = OpenSearchManager().opensearch
    opensearch.indices.update_aliases(
        body={
            'actions': [
                {'remove': {'index': '*', 'alias': args.alias}},
                {'add': {'index': args.add, 'alias': args.alias}},
            ],
        },
    )
    if args.delete:
        opensearch.indices.delete(args.remove)


if __name__ == '__main__':
    main()
